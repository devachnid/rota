"""Pull time off from FindMyShift into the overlay. One transaction, replace-all.

For every team the key can see (or the one FINDMYSHIFT_TEAM_ID names),
fetch the time-off list for a window around today, keep what is approved,
turn each record's start and end into a span of parts, deduplicate on the
content key, and replace the overlay wholesale. A record deleted or
unapproved in FindMyShift is simply absent next time; nothing has to be
reconciled.

FindMyShift does not publish the shape of a time-off record. Measured on a
test account (2026-10-23) it is day-based: `firstDayOff`/`lastDayOff` as
dates, `days` as the weekdays inside that range the time off applies to
(0 = Sunday … 6 = Saturday), `dateApproved` and `dateDeleted` as timestamps
or null, `staffId` (null for time off not assigned to anyone), `type` as
the type's name and `timeOffTypeId` as its id, and `recurrence`,
`recurrenceInterval`, `recursUntil` for a repeating record. There are no
clock times: a day is off or it is not — except by FindMyShift's own
convention for part of a day, which is a whole date described "Morning
off" or "Afternoon off" (half_day below). The fields are still read by name
with alternatives (FIELDS), so a record that has none of the names for a
field it must have fails the run with a message naming the record and the
keys it did carry — values are never reported — which is also what
`findmyshift_sync --inspect` prints for a whole account.
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
    "id": ("timeOffId", "id", "ID"),
    "staff": ("staffId", "staffID", "staff.id", "staffMemberId"),
    "start": ("firstDayOff", "from", "start", "startDate", "dateFrom", "fromDate"),
    "end": ("lastDayOff", "to", "end", "endDate", "dateTo", "toDate"),
    # A timestamp when approved, null while pending — or a plain yes/no.
    "approved": ("dateApproved", "approved", "isApproved", "status"),
    "deleted": ("dateDeleted", "deleted", "cancelled", "isDeleted"),
    # A record names its type by id (the team lists the types) and by name.
    "reason": ("timeOffTypeId", "type", "timeOffType", "typeName", "reason",
               "reasonName", "category"),
    "days": ("days", "weekdays"),
    "recurrence": ("recurrence",),
    # The record's own description — FindMyShift's convention for part of a
    # day ("Morning off", "Afternoon off"). Read for that phrase only, never
    # stored: it defaults to the type's name and can hold anything.
    "description": ("description",),
}
HALF_DAY_WORDS = {
    "AM": re.compile(r"\b(morning|a\.?m\.?)\b", re.I),
    "PM": re.compile(r"\b(afternoon|p\.?m\.?)\b", re.I),
}
TYPE_NAME_KEYS = ("description", "name", "title")
TRUE_WORDS = ("yes", "true", "1", "approved", "y")
FALSE_WORDS = ("no", "false", "0", "", "pending", "declined", "requested", "n", "none", "null")
# FindMyShift's weekday numbering (JavaScript's): Sunday is 0.
ALL_DAYS = frozenset(range(7))
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
    return pick_present(row, field)[1]


def pick_present(row, field):
    """(found, value) for the first key of FIELDS[field] the record carries
    — null included, because for `dateApproved` and `dateDeleted` a null
    is the answer (pending; not deleted), not an absence."""
    for name in FIELDS[field]:
        value, found = row, True
        for part in name.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                found = False
                break
        if found:
            return True, value
    return False, None


def is_deleted(row):
    found, value = pick_present(row, "deleted")
    return found and as_bool(value, default=False)


def is_approved(row):
    """Approved unless the record says otherwise. A record with no approval
    field at all is taken as approved (an account where approval is not in
    use); one with the field null is pending."""
    found, value = pick_present(row, "approved")
    return as_bool(value, default=False) if found else True


def for_no_one(row):
    """A record that has a staff field and nobody in it."""
    found, value = pick_present(row, "staff")
    return found and value is None


def as_bool(value, *, default):
    """A flag from whatever form it takes: a bool, a number, a yes/no word,
    or — as a real account sends `dateApproved` and `dateDeleted` — a
    timestamp, whose presence is the yes."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    word = str(value).strip().lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    return True


def half_day(description):
    """Which half a record's description says is off — "AM" for a morning,
    "PM" for an afternoon — or None for a whole day. FindMyShift records
    time off as whole days; its guide's convention for part of a day is to
    book the whole date and describe it "Morning off" or "Afternoon off".
    A description naming both halves is a whole day."""
    text = str(description or "")
    hits = [half for half, rx in HALF_DAY_WORDS.items() if rx.search(text)]
    return hits[0] if len(hits) == 1 else None


def fms_weekday(day):
    """A date's weekday as FindMyShift numbers it: Sunday 0 … Saturday 6."""
    return (day.weekday() + 1) % 7


def day_runs(start, end, days):
    """The runs of consecutive dates in start..end whose weekday is in
    `days`, as (first, last) pairs. A record's `days` is the weekdays the
    time off applies to; a Monday-to-Friday range with Wednesday unticked
    is two runs, not one."""
    runs, first, prev = [], None, None
    day = start
    while day <= end:
        if fms_weekday(day) in days:
            if first is None:
                first = day
            prev = day
        elif first is not None:
            runs.append((first, prev)); first = None
        day += timedelta(days=1)
    if first is not None:
        runs.append((first, prev))
    return runs


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


def normalise(row, types=None):
    """The Norms a record comes to — one per run of applicable days, or none
    for a record that is not approved leave for a person.

    `types` maps the team's time-off type ids to their names; a record
    naming its type by id gets the name. A record with no approval field
    at all is taken as approved: an account whose records never say so is
    one where approval is not in use, and silently showing nobody as off
    would be the worse error. The inspect command shows which it is. A
    record with no staff member (FindMyShift allows one) is nobody's time
    off and is skipped. A recurring record is stored as its first
    occurrence only and logged: the repeat rule's shape is unmeasured.
    """
    if not isinstance(row, dict):
        raise Unreadable(f"a time-off record is a {type(row).__name__}, not an object")
    source_id = pick(row, "id")
    if is_deleted(row) or not is_approved(row) or for_no_one(row):
        return []
    staff_id = pick(row, "staff")
    start, end = pick(row, "start"), pick(row, "end")
    missing = [f for f, v in (("staff", staff_id), ("start", start), ("end", end)) if v is None]
    if missing:
        raise Unreadable(
            f"time-off record {source_id!r} has no {'/'.join(missing)} field "
            f"(keys present: {sorted(row)}; looked for {[FIELDS[f] for f in missing]})")
    if pick(row, "recurrence") not in (None, "", 0, False):
        log.warning("findmyshift record %s recurs; only its first occurrence is read",
                    source_id)
    days = pick(row, "days")
    days = {int(d) for d in days} if isinstance(days, (list, tuple)) and days else ALL_DAYS
    reason = reason_name(pick(row, "reason"), types or {})
    whole = Span.from_times(parse_when(start), parse_when(end))
    half = half_day(pick(row, "description"))
    if half and whole.start_date == whole.end_date:
        # A morning off ends at midday; an afternoon off starts there.
        whole = Span(whole.start_date, whole.end_date,
                     half == "PM", "PM" if half == "PM" else "",
                     half == "AM", "AM" if half == "AM" else "")
    elif half:
        log.warning("findmyshift record %s is described as a %s off but spans "
                    "%s to %s; read as whole days", source_id,
                    "morning" if half == "AM" else "afternoon",
                    whole.start_date, whole.end_date)
    runs = ([(whole.start_date, whole.end_date)] if days == ALL_DAYS
            else day_runs(whole.start_date, whole.end_date, days))
    out = []
    for first, last in runs:
        span = Span(first, last,
                    whole.half_start if first == whole.start_date else False,
                    whole.half_start_am_pm if first == whole.start_date else "",
                    whole.half_end if last == whole.end_date else False,
                    whole.half_end_am_pm if last == whole.end_date else "")
        out.append(Norm(staff_id=str(staff_id), span=span, reason=reason,
                        source_id=str(source_id)))
    return out


def reason_name(value, types):
    """The reason as a name: a type object's description, a type id looked
    up in the team's types, or the text itself."""
    if isinstance(value, dict):
        value = next((value[k] for k in TYPE_NAME_KEYS if value.get(k)), "")
    text = str(value or "").strip()
    return (types.get(text) or text)[:100]


def team_types(team):
    """{timeOffTypeId: description} from a team record, as a real account
    lists them — deleted types included, since an old record may still
    name one."""
    out = {}
    for t in team.get("timeOffTypes") or []:
        if isinstance(t, dict) and t.get("timeOffTypeId") is not None:
            out[str(t["timeOffTypeId"])] = str(
                next((t[k] for k in TYPE_NAME_KEYS if t.get(k)), t["timeOffTypeId"]))
    return out


def teams(client):
    """The teams to read, as (id, {type id: name}): the configured one,
    else every team the key sees. The listing is always fetched, because
    it is where the time-off types live."""
    out = []
    for team in client.teams():
        if not isinstance(team, dict):
            continue
        tid = team.get("teamId", team.get("id"))
        if tid is None:
            continue
        if settings.FINDMYSHIFT_TEAM_ID and str(tid) != settings.FINDMYSHIFT_TEAM_ID:
            continue
        out.append((str(tid), team_types(team)))
    if not out:
        raise FindMyShiftError(
            "FindMyShift lists no team for this key"
            + (f" matching FINDMYSHIFT_TEAM_ID={settings.FINDMYSHIFT_TEAM_ID}"
               if settings.FINDMYSHIFT_TEAM_ID else "; set FINDMYSHIFT_TEAM_ID if the account has one"),
            method="teams/list")
    return out


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
    """Every time-off record across the teams, each with its team's types."""
    since, until = window(today)
    found = teams(client)
    records = []
    for tid, types in found:
        records.extend((row, types) for row in client.time_off(tid, since, until))
    return found, records


def _run(client, result, *, dry_run):
    try:
        found, records = fetch(client)
    except FindMyShiftError as e:
        result.error = f"fetching {e.method} failed: {e}"
        result.finished = timezone.now()
        if not dry_run:
            result.save()
        return result
    result.n_teams = len(found)
    result.n_records = len(records)

    merged, approved = {}, 0
    for row, types in records:
        norms = normalise(row, types)
        if not norms:
            continue
        approved += 1
        for norm in norms:
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
    record carries, how each field this sync needs resolved, the time-off
    types the account defines and the reasons in use — names only, never a
    value from a record. For the first run against the practice's account,
    and for the day FindMyShift changes something."""
    out = []
    found = teams(client)
    out.append(f"teams: {len(found)}")
    for tid, types in found:
        out.append(f"  team {tid}: time-off types {sorted(types.values())}")
    staff = client.staff(settings.FINDMYSHIFT_TEAM_ID or None)
    out.append(f"staff: {len(staff)} records; "
               f"with an id: {sum(1 for s in staff if s.get('id') is not None)}, "
               f"with an email: {sum(1 for s in staff if s.get('emailAddress'))}")
    since, until = window()
    records = []
    for tid, types in found:
        records.extend((row, types) for row in client.time_off(tid, since, until))
    out.append(f"time off: {len(records)} records between {since} and {until}")
    rows = [r for r, _ in records if isinstance(r, dict)]
    out.append(f"time-off keys: {sorted({k for r in rows for k in r})}")
    for field, names in FIELDS.items():
        used = next((n for n in names if any(_under(r, n) for r in rows)), None)
        out.append(f"  {field}: {'read from ' + repr(used) if used else 'NOT FOUND'}")
    reasons = sorted({reason_name(pick(r, "reason"), t) for r, t in records if isinstance(r, dict)})
    out.append(f"reasons seen: {reasons}")
    out.append(f"approved (or unmarked), not deleted, for a person: "
               f"{sum(1 for r, t in records if isinstance(r, dict) and normalise(r, t))}")
    out.append(f"pending: {sum(1 for r in rows if not is_approved(r))}; "
               f"deleted: {sum(1 for r in rows if is_deleted(r))}; "
               f"for no one: {sum(1 for r in rows if for_no_one(r))}; "
               f"recurring: {sum(1 for r in rows if pick(r, 'recurrence') not in (None, '', 0, False))}; "
               f"with a weekday mask: {sum(1 for r in rows if isinstance(pick(r, 'days'), list) and set(pick(r, 'days')) != ALL_DAYS)}; "
               f"half days by description: {sum(1 for r in rows if half_day(pick(r, 'description')))}")
    return "\n".join(out)


def _under(row, dotted):
    value = row
    for part in dotted.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value is not None
