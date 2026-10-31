"""A start/end pair, read as the rota's AM/PM parts.

The table in rota/services/time_off.py is the whole contract: a
time at or after midday keeps the first morning, a time at or before
midday keeps the last afternoon, anything else on a boundary day is that
whole day, and an end at midnight is the exclusive form of "to the end of
the day before".
"""

from datetime import date, datetime, time

import pytest

from rota.services.time_off import MIDDAY, Span, parts_off

MON, TUE, WED = date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16)


def span(start, end, hs=False, hs_ampm=None, he=False, he_ampm=None):
    return Span(start, end, hs, hs_ampm, he, he_ampm)


# --- from_times -------------------------------------------------------------

def test_an_all_day_record_with_an_inclusive_end_is_whole_days():
    s = Span.from_times(datetime(2026, 9, 14, 0, 0), datetime(2026, 9, 16, 23, 59, 59))
    assert (s.start_date, s.end_date) == (MON, WED)
    assert not s.half_start and not s.half_end
    assert s.half_start_am_pm == "" and s.half_end_am_pm == ""


def test_an_exclusive_midnight_end_means_the_day_before():
    s = Span.from_times(datetime(2026, 9, 14, 0, 0), datetime(2026, 9, 17, 0, 0))
    assert (s.start_date, s.end_date) == (MON, WED)
    assert not s.half_end


def test_dates_with_no_time_are_whole_days():
    s = Span.from_times(MON, WED)
    assert (s.start_date, s.end_date) == (MON, WED)
    assert not s.half_start and not s.half_end


def test_a_start_at_midday_keeps_the_morning():
    s = Span.from_times(datetime(2026, 9, 14, 13, 0), datetime(2026, 9, 14, 17, 0))
    assert s.half_start and s.half_start_am_pm == "PM"
    assert not s.half_end
    assert parts_off(s, MON) == {"PM"}


def test_a_start_after_midday_keeps_the_morning_too():
    s = Span.from_times(datetime(2026, 9, 14, 14, 30), datetime(2026, 9, 15, 23, 59))
    assert parts_off(s, MON) == {"PM"}
    assert parts_off(s, TUE) == {"AM", "PM"}


def test_a_start_in_the_morning_is_the_whole_day():
    """09:00 to 17:00 is not half a day the rota can express; off is the
    safer reading."""
    s = Span.from_times(datetime(2026, 9, 14, 9, 0), datetime(2026, 9, 14, 17, 0))
    assert parts_off(s, MON) == {"AM", "PM"}


def test_an_end_at_midday_keeps_the_afternoon():
    s = Span.from_times(datetime(2026, 9, 14, 0, 0), datetime(2026, 9, 16, 12, 0))
    assert s.half_end and s.half_end_am_pm == "AM"
    assert parts_off(s, WED) == {"AM"}
    assert parts_off(s, TUE) == {"AM", "PM"}


def test_an_end_before_midday_keeps_the_afternoon_too():
    s = Span.from_times(datetime(2026, 9, 14, 0, 0), datetime(2026, 9, 16, 11, 0))
    assert parts_off(s, WED) == {"AM"}


def test_an_end_after_midday_is_the_whole_day():
    s = Span.from_times(datetime(2026, 9, 14, 0, 0), datetime(2026, 9, 16, 17, 0))
    assert not s.half_end
    assert parts_off(s, WED) == {"AM", "PM"}


def test_a_morning_only_single_day():
    s = Span.from_times(datetime(2026, 9, 14, 8, 0), datetime(2026, 9, 14, 12, 0))
    assert parts_off(s, MON) == {"AM"}


def test_midday_is_fixed_at_one_in_the_afternoon():
    assert MIDDAY == time(13, 0)
    s = Span.from_times(datetime(2026, 9, 14, 12, 59), datetime(2026, 9, 14, 17, 0))
    assert parts_off(s, MON) == {"AM", "PM"}, "12:59 is still the morning, so the whole day is off"
    s = Span.from_times(datetime(2026, 9, 14, 13, 0), datetime(2026, 9, 14, 17, 0))
    assert parts_off(s, MON) == {"PM"}


def test_an_end_before_the_start_is_refused():
    with pytest.raises(ValueError):
        Span.from_times(WED, MON)


# --- parts_off --------------------------------------------------------------

def test_a_day_strictly_inside_the_range_is_fully_off():
    assert parts_off(span(MON, WED), TUE) == {"AM", "PM"}


def test_a_day_outside_the_range_is_not_off():
    assert parts_off(span(MON, TUE), WED) == frozenset()
    assert parts_off(span(TUE, WED), MON) == frozenset()


def test_half_flags_only_apply_to_their_own_end():
    s = span(MON, WED, hs=True, hs_ampm="PM", he=True, he_ampm="AM")
    assert parts_off(s, MON) == {"PM"}
    assert parts_off(s, TUE) == {"AM", "PM"}
    assert parts_off(s, WED) == {"AM"}


def test_a_single_day_with_contradictory_flags_is_nothing():
    """Off from the afternoon and until the morning of the same day covers
    no part. Not something to guess at."""
    s = span(MON, MON, hs=True, hs_ampm="PM", he=True, he_ampm="AM")
    assert parts_off(s, MON) == frozenset()


def test_a_half_flag_with_no_am_pm_value_is_treated_as_a_full_day():
    s = span(MON, MON, hs=True, hs_ampm=None)
    assert parts_off(s, MON) == {"AM", "PM"}
    s = span(MON, MON, he=True, he_ampm="")
    assert parts_off(s, MON) == {"AM", "PM"}
