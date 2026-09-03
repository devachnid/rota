"""The half-day truth table from the spec, row by row.

Breathe records a range with four half-day fields. This module is the one
place that turns them into the rota's AM/PM parts, and it is pure, so it is
tested exhaustively here rather than through a screen.
"""

from datetime import date

import pytest

from rota.services.breathe.halfdays import Span, parts_off

MON, TUE, WED = date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16)


def span(start, end, hs=False, hs_ampm=None, he=False, he_ampm=None):
    return Span(start_date=start, end_date=end, half_start=hs,
                half_start_am_pm=hs_ampm, half_end=he, half_end_am_pm=he_ampm)


def test_a_day_strictly_inside_the_range_is_fully_off():
    assert parts_off(span(MON, WED), TUE) == {"AM", "PM"}


def test_a_day_outside_the_range_is_not_off():
    assert parts_off(span(MON, TUE), WED) == frozenset()
    assert parts_off(span(TUE, WED), MON) == frozenset()


def test_a_full_first_day_is_fully_off():
    assert parts_off(span(MON, WED), MON) == {"AM", "PM"}


def test_a_half_start_in_the_afternoon_leaves_the_morning_working():
    assert parts_off(span(MON, WED, hs=True, hs_ampm="PM"), MON) == {"PM"}


def test_a_half_start_in_the_morning_is_a_morning_off():
    assert parts_off(span(MON, WED, hs=True, hs_ampm="AM"), MON) == {"AM"}


def test_a_half_end_in_the_morning_leaves_the_afternoon_working():
    assert parts_off(span(MON, WED, he=True, he_ampm="AM"), WED) == {"AM"}


def test_a_half_end_in_the_afternoon_is_an_afternoon_off():
    assert parts_off(span(MON, WED, he=True, he_ampm="PM"), WED) == {"PM"}


def test_half_flags_only_apply_to_their_own_end():
    """A half start must not shorten the last day, nor a half end the first."""
    s = span(MON, WED, hs=True, hs_ampm="PM", he=True, he_ampm="AM")
    assert parts_off(s, MON) == {"PM"}
    assert parts_off(s, TUE) == {"AM", "PM"}
    assert parts_off(s, WED) == {"AM"}


def test_a_single_day_with_consistent_flags_is_that_one_part():
    assert parts_off(span(MON, MON, hs=True, hs_ampm="AM", he=True, he_ampm="AM"), MON) == {"AM"}
    assert parts_off(span(MON, MON, hs=True, hs_ampm="PM"), MON) == {"PM"}


def test_a_single_day_with_contradictory_flags_is_nothing():
    """AM-start and PM-end on one day cannot both be true. The spec says: no
    parts, and the sync logs it — never guess."""
    assert parts_off(span(MON, MON, hs=True, hs_ampm="AM", he=True, he_ampm="PM"), MON) == frozenset()


def test_a_half_flag_with_no_am_pm_value_is_treated_as_a_full_day():
    """Breathe sends half_start=false with am_pm=null routinely. If it ever
    sends half_start=true with a null am_pm, the record is malformed; erring
    towards 'off all day' keeps someone off the rota rather than on it."""
    assert parts_off(span(MON, WED, hs=True, hs_ampm=None), MON) == {"AM", "PM"}


def test_span_from_api_reads_the_six_breathe_fields():
    row = {"start_date": "2026-09-14", "end_date": "2026-09-16",
           "half_start": True, "half_start_am_pm": "PM",
           "half_end": False, "half_end_am_pm": None, "id": 1, "other": "x"}
    s = Span.from_api(row)
    assert s == span(MON, WED, hs=True, hs_ampm="PM")
