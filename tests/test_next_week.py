"""Which week the assisted fill should offer to start on: from next Monday,
the first week under half filled — working sessions against entries. A few
advance bookings leave a week under half, so it is still wanted; a week
with no working sessions at all is skipped."""

from datetime import date, timedelta

import pytest

from rota.models import ClosedDay, PracticeSettings
from rota.services.next_week import next_monday, suggest
from tests.factories import make_absence, make_clinician, make_entry, make_pattern

pytestmark = pytest.mark.django_db

TODAY = date(2026, 9, 16)          # a Wednesday
NEXT = date(2026, 9, 21)           # the Monday after
WEEK_AFTER = NEXT + timedelta(days=7)


def _gp(name="Alice Adams", parts=("AM", "PM")):
    c = make_clinician(name)
    make_pattern(c, parts=parts)
    return c


def _fill_week(c, monday, parts=("AM", "PM"), days=range(5)):
    for d in days:
        for part in parts:
            make_entry(c, day=monday + timedelta(days=d), part=part)


def test_next_monday_is_strictly_after_today():
    assert next_monday(TODAY) == NEXT
    assert next_monday(NEXT) == WEEK_AFTER


def test_an_empty_rota_suggests_next_monday():
    PracticeSettings.load()
    _gp()
    s = suggest(TODAY)
    assert s.found and s.monday == NEXT
    assert (s.working, s.filled) == (10, 0)


def test_a_few_advance_sessions_still_leave_the_week_wanted():
    PracticeSettings.load()
    c = _gp()
    _fill_week(c, NEXT, parts=("AM",), days=range(2))
    s = suggest(TODAY)
    assert s.monday == NEXT and s.filled == 2


def test_exactly_half_filled_is_not_wanted():
    PracticeSettings.load()
    c = _gp()
    _fill_week(c, NEXT, parts=("AM",))       # 5 of 10
    assert suggest(TODAY).monday == WEEK_AFTER


def test_a_full_week_is_skipped():
    PracticeSettings.load()
    _fill_week(_gp(), NEXT)
    s = suggest(TODAY)
    assert s.monday == WEEK_AFTER and s.filled == 0


def test_a_week_with_every_day_closed_is_skipped():
    PracticeSettings.load()
    _gp()
    for d in range(5):
        ClosedDay.objects.create(day=NEXT + timedelta(days=d), reason="Closed")
    assert suggest(TODAY).monday == WEEK_AFTER


def test_leave_reduces_the_working_count():
    PracticeSettings.load()
    c = _gp()
    make_absence(c, NEXT, NEXT + timedelta(days=4))
    s = suggest(TODAY)
    assert s.monday == WEEK_AFTER and s.working == 10


def test_drafts_count_as_filled():
    PracticeSettings.load()
    c = _gp()
    for d in range(5):
        for part in ("AM", "PM"):
            make_entry(c, day=NEXT + timedelta(days=d), part=part,
                       is_published=False)
    assert suggest(TODAY).monday == WEEK_AFTER


def test_falls_back_to_next_monday_when_no_week_is_under_half():
    PracticeSettings.load()
    c = _gp(parts=("AM",))                   # 5 working sessions a week
    for w in range(26):
        _fill_week(c, NEXT + timedelta(days=7 * w), parts=("AM",), days=range(3))
    s = suggest(TODAY)
    assert not s.found and s.monday == NEXT
    assert s.horizon_end == NEXT + timedelta(days=26 * 7 - 1)


def test_the_scan_is_a_fixed_number_of_queries(django_assert_max_num_queries):
    PracticeSettings.load()
    for name in ("Alice Adams", "Beth Brown", "Cara Cole"):
        _gp(name)
    with django_assert_max_num_queries(8):
        suggest(TODAY)
