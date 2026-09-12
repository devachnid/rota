import pytest

from rota.models import CoverageRule, LocumRequirement, ClosedDay, PracticeSettings
from datetime import timedelta

from rota.services.warnings import day_warnings, week_warnings
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


def test_a_shortfall_says_how_many_of_how_many():
    """"No Routine cover" was the message even at three of four placed,
    which is not what it said. Zero keeps the plain wording; a shortfall
    counts."""
    PracticeSettings.objects.update_or_create(pk=1, defaults={"min_clinical_per_session": 0})
    rout = make_session_type("Routine")
    CoverageRule.objects.create(session_type=rout, count=4)
    for name in ("Ann Ash", "Ben Birch", "Cal Cedar"):
        make_entry(make_clinician(name), part="AM", session_type=rout)
    msgs = {w.part: w.message for w in day_warnings(MON) if w.code == "coverage"}
    assert msgs["AM"] == "Routine 3/4 (AM)"
    assert msgs["PM"] == "No Routine cover (PM)"


def test_a_rule_with_blank_weekdays_is_checked_every_open_day(duty_rule):
    PracticeSettings.objects.update_or_create(pk=1, defaults={"min_clinical_per_session": 0})
    CoverageRule.objects.filter(session_type=duty_rule).update(weekdays="")
    assert [w.part for w in day_warnings(MON) if w.code == "coverage"] == ["AM", "PM"]


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
    make_group("Partner", min_per_session=1, display_order=1)
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


def test_a_need_approved_locum_is_named_in_the_suffix(duty_rule):
    PracticeSettings.objects.update_or_create(pk=1, defaults={"min_clinical_per_session": 0})
    LocumRequirement.objects.create(
        day=MON, part="PM", session_type=duty_rule,
        status=LocumRequirement.Status.APPROVED,
    )
    warnings = [w for w in day_warnings(MON) if w.code == "coverage"]
    assert any(w.message.endswith("— locum need approved") for w in warnings)


def test_group_minimum_ignores_absences():
    PracticeSettings.objects.update_or_create(pk=1, defaults={"min_clinical_per_session": 0})
    partners = make_group("Partner", min_per_session=1, display_order=1)
    c = make_clinician("Alice Adams", group=partners)
    leave = make_session_type("Annual leave", category="ABSENCE")
    make_entry(c, part="AM", session_type=leave)
    assert [w for w in day_warnings(MON) if w.code == "group" and w.part == "AM"]


# --------------------------------------------------------------------------
# ceilings on a session type: max per session / day / week
# --------------------------------------------------------------------------

def _quiet():
    PracticeSettings.objects.update_or_create(pk=1, defaults={"min_clinical_per_session": 0})


def _ceiling(w):
    return [x for x in w if x.code == "ceiling"]


def test_max_per_session_warns_per_part_when_exceeded():
    _quiet()
    urgent = make_session_type("Urgent", max_per_session=1)
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    make_entry(a, part="AM", session_type=urgent)
    assert _ceiling(day_warnings(MON)) == []
    make_entry(b, part="AM", session_type=urgent)
    make_entry(b, part="PM", session_type=urgent)
    [w] = _ceiling(day_warnings(MON))
    assert (w.part, w.message) == ("AM", "Too many Urgent (AM): 2, max 1")


def test_max_per_day_counts_sessions_so_a_full_day_is_two():
    _quiet()
    urgent = make_session_type("Urgent", max_per_day=2)
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    make_entry(a, part="AM", session_type=urgent)
    make_entry(a, part="PM", session_type=urgent)
    assert _ceiling(day_warnings(MON)) == []
    make_entry(b, part="AM", session_type=urgent)
    [w] = _ceiling(day_warnings(MON))
    assert w.part is None and w.message == "Too many Urgent today: 3 sessions, max 2"


def test_a_type_with_no_ceiling_never_warns():
    _quiet()
    routine = make_session_type("Routine")
    for name in ("A One", "B Two", "C Three"):
        make_entry(make_clinician(name), part="AM", session_type=routine)
    assert _ceiling(day_warnings(MON)) == []


def test_max_per_week_is_counted_over_the_open_days_shown():
    _quiet()
    larc = make_session_type("LARC", max_per_week=2)
    days = [MON + timedelta(days=i) for i in range(5)]
    a = make_clinician("Alice Adams")
    make_entry(a, day=days[0], part="AM", session_type=larc)
    make_entry(a, day=days[2], part="AM", session_type=larc)
    assert week_warnings(days) == []
    draft = make_entry(a, day=days[4], part="PM", session_type=larc, is_published=False)
    [w] = week_warnings(days)
    assert w.message == "Too many LARC this week: 3 sessions, max 2"
    # A GP's view has no drafts, and no warning either.
    assert week_warnings(days, include_drafts=False) == []
    ClosedDay.objects.create(day=days[4], reason="Bank holiday")
    assert week_warnings(days) == [], draft


def test_the_week_ceiling_shows_under_the_toolbar_for_an_admin(admin_client, gp_client):
    _quiet()
    larc = make_session_type("LARC", max_per_week=1)
    a = make_clinician("Alice Adams")
    make_entry(a, day=MON, part="AM", session_type=larc)
    make_entry(a, day=MON + timedelta(days=1), part="AM", session_type=larc)
    html = admin_client.get(f"/rota/?week={MON.isoformat()}").content.decode()
    assert "Too many LARC this week: 2 sessions, max 1" in html
    assert "Too many LARC" not in gp_client.get(f"/rota/?week={MON.isoformat()}").content.decode()
