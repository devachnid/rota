"""Pull leave from Breathe into the overlay. One transaction, replace-all.

Three endpoints hold leave and, in the test account, do not agree: two
records appear in both /absences and /leave_requests under different ids,
while other approved requests appear in only one. So: fetch everything from
all three, filter, normalise to a content key, deduplicate on it, and
replace the overlay wholesale. A record cancelled in Breathe is simply
absent next time; nothing has to be reconciled.

Sources are walked in a fixed order and the first row seen for a key keeps
its kind and reason; later collisions contribute only their id.
"""

import logging
from dataclasses import dataclass, replace

from django.db import transaction
from django.utils import timezone

from rota.models import BreatheAbsence, BreatheSyncRun, Clinician
from rota.services.breathe.client import BreatheError
from rota.services.breathe.halfdays import Span, parts_off

log = logging.getLogger("rota.breathe")

SOURCES = ("leave_requests", "absences", "sicknesses")


@dataclass(frozen=True)
class Norm:
    employee_id: int
    span: Span
    kind: str
    reason: str
    source_id: str

    @property
    def key(self):
        s = self.span
        return (self.employee_id, s.start_date, s.end_date, s.half_start,
                s.half_start_am_pm, s.half_end, s.half_end_am_pm)


def _kind_and_reason(row):
    if row.get("type") == "Holiday":
        return BreatheAbsence.Kind.HOLIDAY, ""
    reason = (row.get("leave_reason") or row.get("reason") or {}).get("name") or ""
    return BreatheAbsence.Kind.OTHER, reason


def normalise(source, row):
    """A Norm, or None for a row that is not leave."""
    if row.get("cancelled"):
        return None
    if source == "leave_requests" and row.get("status") != "approved":
        return None
    if source == "sicknesses":
        kind, reason = BreatheAbsence.Kind.SICKNESS, ""  # the type is dropped here
    else:
        kind, reason = _kind_and_reason(row)
    span = Span.from_api(row)
    # Breathe sends null for the half-day am_pm fields on some endpoints and
    # "" on others, for the same shape of record. The stored row coerces to
    # "", so the dedup key has to as well: otherwise two records identical
    # but for null-vs-"" survive dedup as distinct and then collide at
    # insert. Span.from_api itself stays a raw read of what the API sent.
    span = replace(span,
                   half_start_am_pm=span.half_start_am_pm or "",
                   half_end_am_pm=span.half_end_am_pm or "")
    return Norm(employee_id=row["employee"]["id"], span=span,
                kind=kind, reason=reason, source_id=str(row["id"]))


def _warn_on_contradictions(norm):
    s = norm.span
    if s.start_date == s.end_date and not parts_off(s, s.start_date):
        log.warning("breathe record %s for employee %s on %s has contradictory "
                    "half-day flags and covers no parts", norm.source_id,
                    norm.employee_id, s.start_date)


def run(client, *, dry_run=False, now=None):
    """One sync. Always answers with a BreatheSyncRun — never an exception.

    The status page and the timer both read the last run row, so a run that
    died without writing one would leave "last successful sync" pointing at
    an old success while nothing had synced for days. A BreatheError is
    reported with the resource that failed; anything else — a TypeError from
    a null date, an IntegrityError from a collision — is reported by type and
    message. The overlay is never half-written: the replace-all is inside
    transaction.atomic(), which rolls back on the way out.
    """
    started = now or timezone.now()
    result = BreatheSyncRun(started=started)
    try:
        return _run(client, result, dry_run=dry_run)
    except Exception as e:
        # The message can only ever be about Breathe's data or the database;
        # the key is not in scope here and never reaches this string.
        log.warning("breathe sync failed with %s", type(e).__name__)
        result.ok = False
        result.error = f"{type(e).__name__}: {e}"
        result.finished = timezone.now()
        if not dry_run:
            result.save()
        return result


def _run(client, result, *, dry_run):
    fetched = {}
    try:
        for source in SOURCES:
            fetched[source] = client.fetch_all(source)
    except BreatheError as e:
        result.error = f"fetching {source} failed: {e} (x-request-id {e.request_id})"
        result.finished = timezone.now()
        if not dry_run:
            result.save()
        return result

    result.n_requests = len(fetched["leave_requests"])
    result.n_absences = len(fetched["absences"])
    result.n_sicknesses = len(fetched["sicknesses"])

    merged = {}
    for source in SOURCES:
        for row in fetched[source]:
            norm = normalise(source, row)
            if norm is None:
                continue
            held = merged.get(norm.key)
            if held is None:
                merged[norm.key] = norm
                _warn_on_contradictions(norm)
            else:
                merged[norm.key] = Norm(held.employee_id, held.span, held.kind,
                                        held.reason, f"{held.source_id},{norm.source_id}")
    result.n_deduped = len(merged)

    by_employee = {c.breathe_employee_id: c for c in
                   Clinician.objects.exclude(breathe_employee_id=None)}
    rows, unlinked = [], 0
    for norm in merged.values():
        clinician = by_employee.get(norm.employee_id)
        if clinician is None:
            unlinked += 1
            continue
        s = norm.span
        rows.append(BreatheAbsence(
            clinician=clinician, start_date=s.start_date, end_date=s.end_date,
            half_start=s.half_start, half_start_am_pm=s.half_start_am_pm or "",
            half_end=s.half_end, half_end_am_pm=s.half_end_am_pm or "",
            kind=norm.kind, reason=norm.reason, source_ids=norm.source_id))
    result.n_unlinked = unlinked
    result.ok = True
    result.finished = timezone.now()

    if dry_run:
        return result
    with transaction.atomic():
        BreatheAbsence.objects.all().delete()
        BreatheAbsence.objects.bulk_create(rows)
        result.save()
    return result
