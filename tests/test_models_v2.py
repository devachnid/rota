from datetime import date

import pytest

from rota.models import CoverageRule, PracticeSettings, SessionType
from tests.factories import MON, make_session_type

pytestmark = pytest.mark.django_db


def _rule(**kw):
    kw.setdefault("session_type", make_session_type())
    return CoverageRule.objects.create(**kw)


def test_months_blank_means_all_year():
    r = _rule()
    assert r.applies_on(date(2026, 1, 5))   # a Monday in January
    assert r.applies_on(date(2026, 7, 20))  # a Monday in July


def test_months_window_filters():
    winter = _rule(months="10,11,12,1,2,3,4")
    assert winter.applies_on(date(2026, 1, 5))       # Jan Monday: in window
    assert not winter.applies_on(date(2026, 7, 20))  # Jul Monday: out
    assert not winter.applies_on(date(2026, 1, 4))   # Jan Sunday: weekday fails


def test_frequency_defaults_to_per_slot():
    assert _rule().frequency == CoverageRule.Frequency.PER_SLOT


def test_preferred_weekday_list_ordered():
    r = _rule(preferred_weekdays="3,1")
    assert r.preferred_weekday_list() == [3, 1]
    assert _rule().preferred_weekday_list() == []


def test_blocks_same_day_m2m():
    pmc = make_session_type("PMC - Routine")
    duty = make_session_type("Duty", fairness_tracked=True)
    pmc.blocks_same_day.add(duty)
    assert duty in pmc.blocks_same_day.all()
    assert pmc not in duty.blocks_same_day.all()  # asymmetric


def test_practice_settings_type_fks_default_null():
    s = PracticeSettings.load()
    assert s.vts_session_type is None
    assert s.sdl_session_type is None
    assert s.mentoring_session_type is None
