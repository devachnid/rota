"""FindMyShift's time off, turned into the rota's AM/PM parts.

A FindMyShift time-off record is day-based: a first and last day off, with
a single date described "Morning off" or "Afternoon off" for half a day
(sync.normalise reads the description). The rota's unit is the half-day
part, so this is where a record becomes parts. It still reads clock times,
splitting at midday, should a record ever carry them; none measured does.
Everything that asks "is this clinician off on this day, this part?" — the
resolver, and through it every screen and the fill engine — comes here, so
the rules below are the whole contract.

A Span is the stored shape: a date range with four half-day fields, the
same four the overlay keeps so that two records covering the same parts
collide on one content key. `Span.from_times` is the only way one is built
from the API.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.conf import settings

ALL = frozenset({"AM", "PM"})


def midday() -> time:
    """Where the morning ends. Time off that starts at or after it leaves the
    morning working; time off that ends at or before it leaves the afternoon
    working. FINDMYSHIFT_MIDDAY, "13:00" unless the practice's afternoon
    starts elsewhere."""
    return time.fromisoformat(settings.FINDMYSHIFT_MIDDAY)


@dataclass(frozen=True)
class Span:
    start_date: date
    end_date: date
    half_start: bool
    half_start_am_pm: str | None
    half_end: bool
    half_end_am_pm: str | None

    @classmethod
    def from_times(cls, start: datetime | date, end: datetime | date) -> "Span":
        """The parts a start/end pair takes off.

        A date with no time is a whole day at that end. An end at exactly
        midnight on a later day is the exclusive form of "to the end of the
        day before" — FindMyShift's own all-day records are read either way,
        inclusive 23:59 or exclusive 00:00, and land on the same span. A
        start at or after midday keeps the first morning; an end at or
        before midday keeps the last afternoon. Anything else on a boundary
        day is that whole day: a record from 09:00 or to 17:00 is not half
        a day the rota can express, and off is the safer reading.
        """
        noon = midday()
        if isinstance(start, datetime):
            start_date, start_time = start.date(), start.time()
        else:
            start_date, start_time = start, None
        if isinstance(end, datetime):
            end_date, end_time = end.date(), end.time()
            if end_time == time(0) and end_date > start_date:
                end_date, end_time = end_date - timedelta(days=1), None
        else:
            end_date, end_time = end, None
        if end_date < start_date:
            raise ValueError(f"time off ends ({end}) before it starts ({start})")
        half_start = start_time is not None and start_time >= noon
        half_end = end_time is not None and time(0) < end_time <= noon
        return cls(
            start_date=start_date, end_date=end_date,
            half_start=half_start, half_start_am_pm="PM" if half_start else "",
            half_end=half_end, half_end_am_pm="AM" if half_end else "",
        )


def _half(flag: bool, am_pm: str | None) -> frozenset[str]:
    """The parts a half-day flag keeps off. A set flag with no AM/PM value is
    malformed; treating it as a full day keeps the clinician off the rota
    rather than on it, which is the safer error."""
    if not flag or am_pm not in ("AM", "PM"):
        return ALL
    return frozenset({am_pm})


def parts_off(span: Span, day: date) -> frozenset[str]:
    """Which of AM/PM `day` is off for, under `span`.

    Empty outside the range. On the first day the half-start rule applies,
    on the last the half-end rule, and on a single-day span both — so a
    record that starts after midday and ends before it covers no part at
    all, which is right: a clinician off from 14:00 to 11:00 the same day
    is not something to guess at.
    """
    if not (span.start_date <= day <= span.end_date):
        return frozenset()
    parts = ALL
    if day == span.start_date:
        parts &= _half(span.half_start, span.half_start_am_pm)
    if day == span.end_date:
        parts &= _half(span.half_end, span.half_end_am_pm)
    return parts
