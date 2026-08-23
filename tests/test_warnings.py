import pytest

from rota.models import CoverageRule, LocumRequirement, ClosedDay, PracticeSettings
from rota.services.warnings import day_warnings
from tests.factories import (MON, make_clinician, make_entry, make_group,
                             make_session_type)

pytestmark = pytest.mark.django_db


@pytest.fixture
def duty_rule(db):
    duty = make_session_type("Duty", fairness_tracked=True)
    CoverageRule.objects.create(
        session_type=duty, unit=CoverageRule.Unit.PER_DAY, priority=1
    )
    return duty


def test_missing_duty_warns_per_part(duty_rule):
    PracticeSettings.objects.update_or_create(pk=1, defaults={"min_clinical_per_session": 0})
    c = make_clinician()
    make_entry(c, part="AM", session_type=duty_rule)
    warnings = day_warnings(MON)
    assert [w.part for w in warnings if w.code == "coverage"] == ["PM"]
    assert "No Duty cover" in warnings[0].message


def test_locum_status_appended(duty_rule):
    PracticeSettings.objects.update_or_create(pk=1, defaults={"min_clinical_per_session": 0})
    LocumRequirement.objects.create(
        day=MON, part="PM", session_type=duty_rule,
        status=LocumRequirement.Status.ADVERTISED,
    )
    warnings = [w for w in day_warnings(MON) if w.code == "coverage"]
    assert any("locum advertised" in w.message for w in warnings)


def test_min_staffing_counts_clinical_entries():
    PracticeSettings.objects.update_or_create(pk=1, defaults={"min_clinical_per_session": 2})
    c = make_clinician()
    make_entry(c, part="AM", session_type=make_session_type("Routine"))
    warnings = [w for w in day_warnings(MON) if w.code == "staffing"]
    assert any(w.part == "AM" and "1" in w.message for w in warnings)


def test_group_minimum():
    PracticeSettings.objects.update_or_create(pk=1, defaults={"min_clinical_per_session": 0})
    partners = make_group("Partner", min_per_session=1, display_order=1)
    warnings = [w for w in day_warnings(MON) if w.code == "group"]
    assert any("Partner" in w.message for w in warnings)


def test_closed_day_has_no_warnings():
    ClosedDay.objects.create(day=MON, reason="Bank holiday")
    assert day_warnings(MON) == []


def test_drafts_excluded_for_gp_view(duty_rule):
    PracticeSettings.objects.update_or_create(pk=1, defaults={"min_clinical_per_session": 0})
    c = make_clinician()
    make_entry(c, part="AM", session_type=duty_rule, is_published=False)
    make_entry(c, part="PM", session_type=duty_rule, is_published=False)
    assert not [w for w in day_warnings(MON, include_drafts=True) if w.code == "coverage"]
    assert [w for w in day_warnings(MON, include_drafts=False) if w.code == "coverage"]


def test_per_session_single_part_rule():
    PracticeSettings.objects.update_or_create(pk=1, defaults={"min_clinical_per_session": 0})
    baby = make_session_type("Baby clinic")
    CoverageRule.objects.create(session_type=baby, unit=CoverageRule.Unit.PER_SESSION,
                                parts="AM", weekdays="0")
    warnings = [w for w in day_warnings(MON) if w.code == "coverage"]
    assert [w.part for w in warnings] == ["AM"]


def test_per_week_quota_rule_produces_no_day_warning():
    # A PER_WEEK quota rule's count is a weekly total, not a per-day
    # requirement, so an empty day must not warn even though `have < count`.
    PracticeSettings.objects.update_or_create(pk=1, defaults={"min_clinical_per_session": 0})
    vas = make_session_type("Vas Clinic", fairness_tracked=True)
    CoverageRule.objects.create(
        session_type=vas, unit=CoverageRule.Unit.PER_SESSION,
        frequency=CoverageRule.Frequency.PER_WEEK, count=2,
        weekdays="0,1,2,3,4", priority=5)
    warnings = [w for w in day_warnings(MON) if w.code == "coverage"]
    assert warnings == []


def test_per_slot_rule_still_warns_alongside_per_week_rule():
    # A PER_SLOT rule on the same shape of session type must still warn.
    PracticeSettings.objects.update_or_create(pk=1, defaults={"min_clinical_per_session": 0})
    coil = make_session_type("Coil Clinic", fairness_tracked=True)
    CoverageRule.objects.create(
        session_type=coil, unit=CoverageRule.Unit.PER_SESSION,
        frequency=CoverageRule.Frequency.PER_SLOT, count=1,
        weekdays="0,1,2,3,4", priority=5)
    warnings = [w for w in day_warnings(MON) if w.code == "coverage"]
    assert any("Coil Clinic" in w.message for w in warnings)


def test_group_minimum_ignores_absences():
    PracticeSettings.objects.update_or_create(pk=1, defaults={"min_clinical_per_session": 0})
    partners = make_group("Partner", min_per_session=1, display_order=1)
    c = make_clinician("Alice Adams", group=partners)
    leave = make_session_type("Annual leave", category="ABSENCE")
    make_entry(c, part="AM", session_type=leave)
    assert [w for w in day_warnings(MON) if w.code == "group" and w.part == "AM"]
