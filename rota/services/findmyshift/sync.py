"""Pull time off from FindMyShift into the overlay. One transaction, replace-all.

For every team the key can see (or the one FINDMYSHIFT_TEAM_ID names),
fetch the time-off list for a window around today, keep what is approved,
turn each record's start and end into a span of parts, deduplicate on the
content key, and replace the overlay wholesale. A record deleted or
unapproved in FindMyShift is simply absent next time; nothing has to be
reconciled.

FindMyShift does not publish the shape of a time-off record, so the fields
are read by name with alternatives (FIELDS). A record that has none of the
names for a field it must have fails the run with a message naming the
record and the keys it did carry — values are never reported — which is
also what `findmyshift_sync --inspect` prints for a whole account.
"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from rota.models import Clinician, TimeOff, TimeOffSyncRun
from rota.services.findmyshift.client import FindMyShiftError
from rota.services.findmyshift.spans import Span

log = logging.getLogger("rota.findmyshift")

# The window fetched, around today. Time off further back is history the
# rota no longer shows; further ahead nobody has booked.
HISTORY_DAYS = 365
HORIZON_DAYS = 730

# The names a field may come under, tried in order. A dotted name reads a
# nested object. The free-text comment on a record is deliberately not here.
FIELDS = {
    "id": ("id", "timeOffId", "ID"),
    "staff": ("staffId", "staffID", "staff.id", "staffMemberId"),
    "start": ("from", "start", "startDate", "dateFrom", "fromDate", "start_date"),
    "end": ("to", "end", "endDate", "dateTo", "toDate", "end_date"),
    "approved": ("approved", "isApproved", "status"),
    "deleted": ("deleted", "cancelled", "isDeleted"),
    "reason": ("reason", "reasonName", "type", "typeName", "timeOffType", "category"),
}
TRUE_WORDS = ("yes", "true", "1", "approved", "y")
_DOTNET_DATE = re.compile(r"/Date\((-?\d+)(?:[+-]\d{4})?\)/")


@dataclass(frozen=True)
class Norm:
    staff_id: str
    span: Span
    reason: str
    source_id: str

    @property
    def key(self):
        s = self.span
        return (self.staff_id, s.start_date, s.end_date, s.half_start,
                s.half_start_am_pm, s.half_end, s.half_end_am_pm)


class Unreadable(Exception):
    """A record the sync cannot read: which field, and the keys it carried."""


def pick(row, field):
    """The first present, non-null value under any of FIELDS[field]."""
    for name in FIELDS[field]:
        value = row
        for part in name.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value is not None:
            return value
    return None


def as_bool(value, *, default):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in TRUE_WORDS


def parse_when(value):
    """A date or a datetime from what FindMyShift sends: ISO 8601 with or
    without a time, with a space or a T, with or without seconds, or the
    old .NET "/Date(ms)/" form. A value that names its offset (a trailing
    Z, +01:00, or the epoch form, which is UTC) is moved to the practice's
    clock (TIME_ZONE) and the offset dropped; a naive one is taken as
    already on it, which is what a team's own times are."""
    if isinstance(value, datetime):
        return _local(value)
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e11 else value
        return _local(datetime.fromtimestamp(seconds, tz=UTC))
    text = str(value).strip()
    m = _DOTNET_DATE.fullmatch(text)
    if m:
        return _local(datetime.fromtimestamp(int(m.group(1)) / 1000, tz=UTC))
    if len(text) == 10:
        return date.fromisoformat(text)
    return _local(datetime.fromisoformat(text.replace("Z", "+00:00")))


def _local(dt):
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(ZoneInfo(settings.TIME_ZONE)).replace(tzinfo=None)


def normalise(row):
    """A Norm, or None for a record that is not approved leave.

    A record with no approval field at all is taken as approved: an
    account whose records never say so is one where approval is not in
    use, and silently showing nobody as off would be the worse error. The
    inspect command shows which it is.
    """
    if not isinstance(row, dict):
        raise Unreadable(f"a time-off record is a {type(row).__name__}, not an object")
    source_id = pick(row, "id")
    if as_bool(pick(row, "deleted"), default=False):
        return None
    if not as_bool(pick(row, "approved"), default=True):
        return None
    staff_id = pick(row, "staff")
    start, end = pick(row, "start"), pick(row, "end")
    missing = [f for f, v in (("staff", staff_id), ("start", start), ("end", end)) if v is None]
    if missing:
        raise Unreadable(
            f"time-off record {source_id!r} has no {'/'.join(missing)} field "
            f"(keys present: {sorted(row)}; looked for {[FIELDS[f] for f in missing]})")
    span = Span.from_times(parse_when(start), parse_when(end))
    reason = pick(row, "reason")
    if isinstance(reason, dict):
        reason = reason.get("name") or reason.get("title") or ""
    return Norm(staff_id=str(staff_id), span=span,
                reason=str(reason or "").strip()[:100], source_id=str(source_id))


def team_ids(client):
    """The teams to read: the configured one, else every team the key sees."""
    if settings.FINDMYSHIFT_TEAM_ID:
        return [settings.FINDMYSHIFT_TEAM_ID]
    ids = []
    for team in client.teams():
        tid = pick(team, "id") if isinstance(team, dict) else None
        if tid is None and isinstance(team, dict):
            tid = team.get("teamId")
        if tid is not None:
            ids.append(str(tid))
    if not ids:
        raise FindMyShiftError("FindMyShift lists no team for this key; set "
                               "FINDMYSHIFT_TEAM_ID if the account has one",
                               method="teams/list")
    return ids


def window(today=None):
    today = today or date.today()
    return today - timedelta(days=HISTORY_DAYS), today + timedelta(days=HORIZON_DAYS)


def run(client, *, dry_run=False, now=None):
    """One sync. Always answers with a TimeOffSyncRun — never an exception.

    The status page and the timer both read the last run row, so a run that
    died without writing one would leave "last successful sync" pointing at
    an old success while nothing had synced for days. A FindMyShiftError is
    reported with the method that failed; an unreadable record by name;
    anything else — an IntegrityError from a collision — by type and
    message. The overlay is never half-written: the replace-all is inside
    transaction.atomic(), which rolls back on the way out.
    """
    started = now or timezone.now()
    result = TimeOffSyncRun(started=started)
    try:
        return _run(client, result, dry_run=dry_run)
    except Exception as e:
        # Meant to be about FindMyShift's data or the database. But the
        # message is whatever the exception says, and it is shown to every
        # rota admin, so the key is struck out of it whatever raised it.
        log.warning("findmyshift sync failed with %s", type(e).__name__)
        result.ok = False
        result.error = _redacted(f"{type(e).__name__}: {e}")
        result.finished = timezone.now()
        if not dry_run:
            result.save()
        return result


def _redacted(text):
    key = settings.FINDMYSHIFT_API_KEY
    return text.replace(key, "[FINDMYSHIFT_API_KEY]") if key else text


def fetch(client, today=None):
    """Every time-off record across the teams, with the team count."""
    since, until = window(today)
    teams = team_ids(client)
    records = []
    for team in teams:
        records.extend(client.time_off(team, since, until))
    return teams, records


def _run(client, result, *, dry_run):
    try:
        teams, records = fetch(client)
    except FindMyShiftError as e:
        result.error = f"fetching {e.method} failed: {e}"
        result.finished = timezone.now()
        if not dry_run:
            result.save()
        return result
    result.n_teams = len(teams)
    result.n_records = len(records)

    merged, approved = {}, 0
    for row in records:
        norm = normalise(row)
        if norm is None:
            continue
        approved += 1
        held = merged.get(norm.key)
        if held is None:
            merged[norm.key] = norm
        else:
            # The first record seen for a span keeps its reason; a later
            # twin contributes only its id.
            merged[norm.key] = Norm(held.staff_id, held.span, held.reason or norm.reason,
                                    f"{held.source_id},{norm.source_id}")
    result.n_approved = approved
    result.n_deduped = len(merged)

    by_staff = {c.findmyshift_staff_id: c for c in
                Clinician.objects.exclude(findmyshift_staff_id=None)}
    rows, unlinked = [], 0
    for norm in merged.values():
        clinician = by_staff.get(norm.staff_id)
        if clinician is None:
            unlinked += 1
            continue
        s = norm.span
        rows.append(TimeOff(
            clinician=clinician, start_date=s.start_date, end_date=s.end_date,
            half_start=s.half_start, half_start_am_pm=s.half_start_am_pm or "",
            half_end=s.half_end, half_end_am_pm=s.half_end_am_pm or "",
            reason=norm.reason, source_ids=norm.source_id[:100]))
    result.n_unlinked = unlinked
    result.ok = True
    result.finished = timezone.now()

    if dry_run:
        return result
    with transaction.atomic():
        TimeOff.objects.all().delete()
        TimeOff.objects.bulk_create(rows)
        result.save()
    return result


def inspect(client):
    """What a real account's records look like: the keys each sort of
    record carries, how each field this sync needs resolved, and the
    reasons in use — names only, never a value from a record. For the
    first run against the practice's account, and for the day FindMyShift
    changes something."""
    out = []
    teams = team_ids(client)
    out.append(f"teams: {len(teams)}")
    staff = client.staff(None if not settings.FINDMYSHIFT_TEAM_ID else teams[0])
    out.append(f"staff: {len(staff)} records; "
               f"with an id: {sum(1 for s in staff if s.get('id') is not None)}, "
               f"with an email: {sum(1 for s in staff if s.get('emailAddress'))}")
    since, until = window()
    records = []
    for team in teams:
        records.extend(client.time_off(team, since, until))
    out.append(f"time off: {len(records)} records between {since} and {until}")
    keys = sorted({k for r in records if isinstance(r, dict) for k in r})
    out.append(f"time-off keys: {keys}")
    for field, names in FIELDS.items():
        found = next((n for n in names
                      if any(_under(r, n) for r in records if isinstance(r, dict))), None)
        out.append(f"  {field}: {'read from ' + repr(found) if found else 'NOT FOUND'}")
    reasons = sorted({str(pick(r, "reason") or "") for r in records if isinstance(r, dict)})
    out.append(f"reasons seen: {reasons}")
    approved = sum(1 for r in records if isinstance(r, dict) and normalise(r) is not None)
    out.append(f"approved (or unmarked) and not deleted: {approved}")
    return "\n".join(out)


def _under(row, dotted):
    value = row
    for part in dotted.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value is not None
