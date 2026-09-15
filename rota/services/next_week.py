"""The week the assisted fill should offer to start on.

The rota is built four to six weeks ahead, so "next Monday" is nearly
always a week already done. From next Monday, this finds the first week
that is under half filled: the number of working sessions — a clinician
who is active, inside their dates, works that half-day by pattern and is
not on Breathe leave — against how many of those hold any entry, draft or
published. A few advance bookings or a booked locum leave a week well
under half, so it is still picked; a week with no working sessions at all
(every day closed) is skipped. Bounded at HORIZON_WEEKS, falling back to
next Monday.

Deliberately not the fill engine's FillContext: that is built for a run
over a range, and this is a scan.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from rota.models import (BreatheAbsence, BreatheLeaveMapping, Clinician,
                         ClosedDay, PatternSlot, PracticeSettings, RotaEntry)
from rota.services import availability

HORIZON_WEEKS = 26


@dataclass(frozen=True)
class Suggestion:
    monday: date
    working: int
    filled: int
    found: bool
    horizon_end: date


def next_monday(today):
    """The Monday strictly after `today` (a Monday jumps a full week)."""
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def suggest(today=None):
    today = today or date.today()
    first = next_monday(today)
    last = first + timedelta(days=HORIZON_WEEKS * 7 - 1)
    open_weekdays = set(PracticeSettings.load().open_weekday_list())
    closed = set(ClosedDay.objects.filter(day__range=(first, last))
                 .values_list("day", flat=True))
    active = list(Clinician.objects.filter(active=True))
    pattern_rows = list(PatternSlot.objects.filter(clinician__in=active)
                        .order_by("effective_from"))
    absences = list(BreatheAbsence.objects.filter(
        clinician__in=active, start_date__lte=last, end_date__gte=first))
    resolver = availability.AvailabilityResolver(
        pattern_rows, active, absences, BreatheLeaveMapping.as_dict())
    held = set(RotaEntry.objects.filter(day__range=(first, last))
               .values_list("clinician_id", "day", "part"))

    for i in range(HORIZON_WEEKS):
        monday = first + timedelta(days=7 * i)
        working = filled = 0
        for offset in range(7):
            day = monday + timedelta(days=offset)
            if day.weekday() not in open_weekdays or day in closed:
                continue
            for c in active:
                for part in ("AM", "PM"):
                    if resolver.available(c.id, day, part):
                        working += 1
                        if (c.id, day, part) in held:
                            filled += 1
        if working and filled * 2 < working:
            return Suggestion(monday, working, filled, True, last)
    return Suggestion(first, 0, 0, False, last)
