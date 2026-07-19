from datetime import date, timedelta

import pytest

from rota.models import ClosedDay, PracticeSettings
from rota.services import availability, calendar
from tests.factories import MON, make_clinician, make_pattern

pytestmark = pytest.mark.django_db


def test_no_pattern_means_not_working():
    c = make_clinician()
    assert not availability.works_on(c, MON, "AM")


def test_pattern_marks_working_sessions():
    c = make_clinician()
    make_pattern(c, weekdays=(0,), parts=("AM",))
    assert availability.works_on(c, MON, "AM")
    assert not availability.works_on(c, MON, "PM")
    assert not availability.works_on(c, MON + timedelta(days=1), "AM")


def test_latest_effective_row_wins():
    c = make_clinician()
    make_pattern(c, weekdays=(0,), parts=("AM",), effective_from=date(2020, 1, 1))
    make_pattern(c, weekdays=(0,), parts=("AM",), works=False,
                 effective_from=date(2026, 7, 1))
    assert not availability.works_on(c, MON, "AM")
    assert availability.works_on(c, date(2026, 6, 1), "AM")


def test_weekly_sessions_counts_current_pattern():
    c = make_clinician()
    make_pattern(c, weekdays=(0, 1), parts=("AM", "PM"))
    assert availability.weekly_sessions(c, MON) == 4


def test_is_open_respects_weekends_and_closures():
    PracticeSettings.load()
    assert calendar.is_open(MON)
    assert not calendar.is_open(MON + timedelta(days=5))  # Saturday
    ClosedDay.objects.create(day=MON, reason="Bank holiday")
    assert not calendar.is_open(MON)
