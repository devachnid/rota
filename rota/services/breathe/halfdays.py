"""Breathe's half-day fields, turned into the rota's AM/PM parts.

A Breathe record is a date range with four extra fields: whether the first
day is a half day and which half, and the same for the last. This is the one
place that reads them. Everything that asks "is this clinician off on this
day, this part?" — the resolver, and through it every screen and the fill
engine — comes here, so the table below is the whole contract.
"""

from dataclasses import dataclass
from datetime import date

ALL = frozenset({"AM", "PM"})


@dataclass(frozen=True)
class Span:
    start_date: date
    end_date: date
    half_start: bool
    half_start_am_pm: str | None
    half_end: bool
    half_end_am_pm: str | None

    @classmethod
    def from_api(cls, row: dict) -> "Span":
        return cls(
            start_date=date.fromisoformat(row["start_date"]),
            end_date=date.fromisoformat(row["end_date"]),
            half_start=bool(row.get("half_start")),
            half_start_am_pm=row.get("half_start_am_pm"),
            half_end=bool(row.get("half_end")),
            half_end_am_pm=row.get("half_end_am_pm"),
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
    on the last the half-end rule, and on a single-day span both — so
    contradictory flags (AM-start, PM-end) intersect to nothing, which is
    what the spec asks for: a Breathe data error is not something to guess at.
    """
    if not (span.start_date <= day <= span.end_date):
        return frozenset()
    parts = ALL
    if day == span.start_date:
        parts &= _half(span.half_start, span.half_start_am_pm)
    if day == span.end_date:
        parts &= _half(span.half_end, span.half_end_am_pm)
    return parts
