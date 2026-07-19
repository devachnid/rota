from datetime import timedelta

import pytest

from rota.models import CoverageRule, PracticeSettings, RotaEntry
from rota.services import entries as entries_svc
from rota.services.fill import run_fill
from tests.factories import (MON, make_clinician, make_entry, make_pattern,
                             make_session_type)

pytestmark = pytest.mark.django_db
FRI = MON + timedelta(days=4)


@pytest.fixture
def duty(db):
    d = make_session_type("Duty", fairness_tracked=True)
    CoverageRule.objects.create(session_type=d, unit=CoverageRule.Unit.PER_DAY,
                                priority=1)
    return d


def test_fill_covers_every_open_day_with_linked_pairs(duty, admin_user):
    a = make_clinician("Alice Adams")
    make_pattern(a)
    result = run_fill(admin_user, MON, FRI)
    assert result.created == 10 and not result.unfilled
    for e in RotaEntry.objects.all():
        assert not e.is_published and not e.manually_set
        assert e.allocation_group and e.fill_reason


def test_part_timer_gets_weighted_share(duty, admin_user):
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    make_pattern(a)                      # 10 sessions/week
    make_pattern(b, weekdays=(0, 1))     # 4 sessions/week, Mon+Tue only
    run_fill(admin_user, MON, FRI)
    b_days = set(RotaEntry.objects.filter(clinician=b).values_list("day", flat=True))
    assert b_days == {MON + timedelta(days=1)}  # Alice Mon (name tie-break), Beth Tue


def test_respects_eligibility_and_leave(duty, admin_user):
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    make_pattern(a)
    make_pattern(b)
    duty.allowed_clinicians.add(b)  # only Beth may do duty
    leave = make_session_type("Annual leave", category="ABSENCE")
    make_entry(b, day=MON, part="AM", session_type=leave)  # Beth off Mon AM
    result = run_fill(admin_user, MON, MON + timedelta(days=1))
    assert [u.day for u in result.unfilled] == [MON]
    assert set(RotaEntry.objects.filter(session_type=duty)
               .values_list("clinician", flat=True)) == {b.id}


def test_rerun_replaces_own_drafts_but_keeps_manual(duty, admin_user):
    a = make_clinician("Alice Adams")
    make_pattern(a)
    routine = make_session_type("Routine")
    entries_svc.assign(admin_user, a, MON, "AM", routine)  # manual draft
    run_fill(admin_user, MON, FRI)
    first_ids = set(RotaEntry.objects.filter(manually_set=False)
                    .values_list("id", flat=True))
    run_fill(admin_user, MON, FRI)
    assert RotaEntry.objects.filter(day=MON, part="AM", clinician=a,
                                    session_type=routine).exists()
    assert not first_ids & set(RotaEntry.objects.filter(manually_set=False)
                               .values_list("id", flat=True))


def test_default_fill_pass(duty, admin_user):
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    make_pattern(a)
    make_pattern(b)
    routine = make_session_type("Routine")
    s = PracticeSettings.load()
    s.default_fill_session_type = routine
    s.save()
    run_fill(admin_user, MON, FRI, fill_default=True)
    # 2 clinicians x 10 sessions, all filled: duty for one, routine for the rest
    assert RotaEntry.objects.count() == 20
    assert RotaEntry.objects.filter(session_type=routine).count() == 10


def test_fill_skips_slots_already_covered(duty, admin_user):
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    make_pattern(a)
    make_pattern(b)
    entries_svc.assign_full_day(admin_user, a, MON, duty, published=True)
    run_fill(admin_user, MON, MON + timedelta(days=1))
    mon_duty = RotaEntry.objects.filter(day=MON, session_type=duty)
    assert set(mon_duty.values_list("clinician", flat=True)) == {a.id}
    tue = MON + timedelta(days=1)
    assert RotaEntry.objects.filter(day=tue, session_type=duty).count() == 2


def test_published_fill_drafts_survive_rerun(duty, admin_user):
    a = make_clinician("Alice Adams")
    make_pattern(a)
    run_fill(admin_user, MON, FRI)
    entries_svc.publish_range(admin_user, MON, FRI)
    ids = set(RotaEntry.objects.values_list("id", flat=True))
    result = run_fill(admin_user, MON, FRI)
    assert set(RotaEntry.objects.values_list("id", flat=True)) == ids
    assert result.created == 0


def test_per_session_rule_rotates_and_fills_count(admin_user):
    visits = make_session_type("Visits")
    CoverageRule.objects.create(session_type=visits,
                                unit=CoverageRule.Unit.PER_SESSION,
                                parts="AM", weekdays="1", count=2, priority=5)
    a, b, c = (make_clinician("Alice Adams"), make_clinician("Beth Brown"),
               make_clinician("Cara Cole"))
    for cl in (a, b, c):
        make_pattern(cl)
    tue = MON + timedelta(days=1)
    run_fill(admin_user, MON, FRI)
    week1 = set(RotaEntry.objects.filter(day=tue, part="AM", session_type=visits)
                .values_list("clinician", flat=True))
    assert len(week1) == 2
    assert not RotaEntry.objects.filter(session_type=visits).exclude(day=tue).exists()
    run_fill(admin_user, MON + timedelta(days=7), FRI + timedelta(days=7))
    week2 = set(RotaEntry.objects.filter(day=tue + timedelta(days=7), part="AM",
                                         session_type=visits)
                .values_list("clinician", flat=True))
    assert len(week2) == 2
    assert ({a.id, b.id, c.id} - week1) < week2


def test_one_fairness_allocation_per_day(admin_user):
    am_t = make_session_type("Triage AM", fairness_tracked=True)
    pm_t = make_session_type("Triage PM", fairness_tracked=True)
    CoverageRule.objects.create(session_type=am_t,
                                unit=CoverageRule.Unit.PER_SESSION,
                                parts="AM", weekdays="0", count=1, priority=1)
    CoverageRule.objects.create(session_type=pm_t,
                                unit=CoverageRule.Unit.PER_SESSION,
                                parts="PM", weekdays="0", count=1, priority=2)
    a = make_clinician("Alice Adams")
    make_pattern(a)
    result = run_fill(admin_user, MON, MON)
    assert RotaEntry.objects.filter(day=MON, session_type=am_t).count() == 1
    assert not RotaEntry.objects.filter(day=MON, session_type=pm_t).exists()
    assert any(u.session_type == "Triage PM" for u in result.unfilled)


def test_manual_partial_duty_gets_topped_up_not_doubled(duty, admin_user):
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    make_pattern(a)
    make_pattern(b)
    entries_svc.assign(admin_user, a, MON, "AM", duty, published=True)
    entries_svc.assign(admin_user, a, MON, "PM", duty, published=True)
    run_fill(admin_user, MON, MON)
    assert set(RotaEntry.objects.filter(day=MON, session_type=duty)
               .values_list("clinician", flat=True)) == {a.id}
