"""One sync: fetch the window, match each record to a clinician by the
login email (lowercased), turn parts into the rota's Span, replace the
TimeOff table in full. Never raises; a failed run keeps the previous rows.
Emails are record values: in `detail`, never in `error` or a log line."""

import logging
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from rota.models import Clinician, TimeOff, TimeOffSyncRun
from rota.services.shift_central.client import ShiftCentralError
from rota.services.time_off import Span

log = logging.getLogger("rota.shift_central")
HISTORY_DAYS, HORIZON_DAYS = 365, 730


class BadRecord(Exception):
    pass


def window(today=None):
    today = today or timezone.localdate()
    return today - timedelta(days=HISTORY_DAYS), today + timedelta(days=HORIZON_DAYS)


def _span(record, position):
    try:
        first, last = date.fromisoformat(record["first_day"]), date.fromisoformat(record["last_day"])
        part = str(record["part"])
        if part not in ("whole", "am", "pm") or last < first or (part != "whole" and first != last):
            raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise BadRecord(f"record {position} in the feed: missing or bad email, days or part") from None
    return Span(first, last, half_start=(part == "pm"), half_start_am_pm="PM" if part == "pm" else "",
                half_end=(part == "am"), half_end_am_pm="AM" if part == "am" else "")


def _clinicians():
    out = {}
    for c in Clinician.objects.filter(active=True).exclude(user=None).select_related("user").order_by("pk"):
        if c.user.email:
            out.setdefault(c.user.email.lower(), c)
    return out


def run(client, *, dry_run=False, now=None):
    now = now or timezone.now()
    result = TimeOffSyncRun(started=now)
    try:
        return _run(client, result, dry_run=dry_run, today=timezone.localtime(now).date())
    except Exception as e:
        log.warning("shift central sync failed with %s", type(e).__name__)
        result.ok, result.error, result.finished = False, f"{type(e).__name__}: {e}"[:500], timezone.now()
        if not dry_run:
            result.save()
        return result


def _run(client, result, *, dry_run, today):
    start, end = window(today)
    try:
        payload = client.leave(start, end)
    except ShiftCentralError as e:
        result.error, result.finished = str(e), timezone.now()
        if not dry_run:
            result.save()
        return result
    by_email = _clinicians()
    rows, keys, unmatched, matched = [], set(), set(), set()
    outside = 0
    for position, record in enumerate(payload["leave"], start=1):
        try:
            email = str(record["email"]).strip().lower()
        except (KeyError, TypeError, AttributeError):
            raise BadRecord(f"record {position} in the feed: missing email") from None
        span = _span(record, position)
        if span.end_date < start or span.start_date > end:
            outside += 1
            continue
        clinician = by_email.get(email)
        if clinician is None:
            unmatched.add(email)
            continue
        key = (clinician.pk, span.start_date, span.end_date, span.half_start, span.half_start_am_pm, span.half_end, span.half_end_am_pm)
        if key in keys:
            continue
        keys.add(key)
        matched.add(clinician.pk)
        rows.append(TimeOff(clinician=clinician, start_date=span.start_date, end_date=span.end_date, half_start=span.half_start,
                            half_start_am_pm=span.half_start_am_pm or "", half_end=span.half_end, half_end_am_pm=span.half_end_am_pm or "",
                            reason=str(record.get("type") or "")[:100], source_ids=span.start_date.isoformat()))
    result.n_records, result.n_matched, result.n_unmatched, result.n_outside = len(payload["leave"]), len(matched), len(unmatched), outside
    result.detail = {"unmatched": sorted(unmatched)}
    result.ok, result.finished = True, timezone.now()
    if dry_run:
        return result
    with transaction.atomic():
        TimeOff.objects.all().delete()
        TimeOff.objects.bulk_create(rows)
        result.save()
    return result


def unmatched_emails():
    last = TimeOffSyncRun.objects.filter(ok=True).first()
    return list((last.detail or {}).get("unmatched", [])) if last else []

