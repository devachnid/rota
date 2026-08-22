from datetime import date, timedelta

import pytest

from rota.models import CoverageRule, PracticeSettings, RotaEntry
from rota.services.fill import run_fill
from tests.factories import (MON, make_clinician, make_pattern,
                             make_session_type)

pytestmark = pytest.mark.django_db
FRI = MON + timedelta(days=4)


def _pool(*names):
    out = []
    for n in names:
        c = make_clinician(n)
        make_pattern(c)
        out.append(c)
    return out


def test_per_week_full_day_preferred_lands_on_thursday(admin_user):
    PracticeSettings.load()
    vas = make_session_type("Vas Clinic", fairness_tracked=True)
    a, b = _pool("Alice Adams", "Beth Brown")
    vas.allowed_clinicians.add(a, b)
    CoverageRule.objects.create(
        session_type=vas, unit=CoverageRule.Unit.FULL_DAY_PREFERRED,
        frequency=CoverageRule.Frequency.PER_WEEK, count=2,
        weekdays="0,1,2,3,4", preferred_weekdays="3,1", priority=5)
    run_fill(admin_user, MON, FRI)
    entries = RotaEntry.objects.filter(session_type=vas)
    assert entries.count() == 2
    thursday = MON + timedelta(days=3)
    assert set(entries.values_list("day", flat=True)) == {thursday}
    groups = set(entries.values_list("allocation_group", flat=True))
    assert len(groups) == 1 and None not in groups  # one clinician, full day


def test_full_day_preferred_splits_when_no_full_day_possible(admin_user):
    PracticeSettings.load()
    vas = make_session_type("Vas Clinic", fairness_tracked=True)
    a = make_clinician("Alice Adams")
    make_pattern(a, weekdays=(1, 3), parts=("AM",))  # Tue+Thu mornings only
    vas.allowed_clinicians.add(a)
    CoverageRule.objects.create(
        session_type=vas, unit=CoverageRule.Unit.FULL_DAY_PREFERRED,
        frequency=CoverageRule.Frequency.PER_WEEK, count=2,
        weekdays="0,1,2,3,4", preferred_weekdays="3,1", priority=5)
    run_fill(admin_user, MON, FRI)
    entries = RotaEntry.objects.filter(session_type=vas).order_by("day")
    assert entries.count() == 2
    assert [(e.day.weekday(), e.part) for e in entries] == [(1, "AM"), (3, "AM")]
    assert all(e.allocation_group is None for e in entries)


def test_per_month_cadence_places_on_accrual(admin_user):
    PracticeSettings.load()
    coil = make_session_type("Coil Clinic", fairness_tracked=True)
    a = make_clinician("Alice Adams")
    make_pattern(a)
    coil.allowed_clinicians.add(a)
    CoverageRule.objects.create(
        session_type=coil, unit=CoverageRule.Unit.PER_SESSION,
        frequency=CoverageRule.Frequency.PER_MONTH, count=2,
        weekdays="0,1,2,3,4", priority=5)
    # rate = 2*12/52.18 = 0.4599/wk. Epoch = Mon of the 1 Jan 2026 week
    # (2025-12-29); MON is week 30 since epoch. Incremental weekly dues
    # (floor(rate*w) diffs) for weeks 30..37 are 0,1,0,1,0,1,0,1 -> exactly 4
    # placements over this 8-week fill, deterministically.
    run_fill(admin_user, MON, MON + timedelta(days=55))
    assert RotaEntry.objects.filter(session_type=coil).count() == 4


def test_quota_counts_existing_manual_entries(admin_user):
    from rota.services import entries as entries_svc
    PracticeSettings.load()
    coil = make_session_type("Coil Clinic", fairness_tracked=True)
    a = make_clinician("Alice Adams")
    make_pattern(a)
    coil.allowed_clinicians.add(a)
    CoverageRule.objects.create(
        session_type=coil, unit=CoverageRule.Unit.PER_SESSION,
        frequency=CoverageRule.Frequency.PER_WEEK, count=1,
        weekdays="0,1,2,3,4", priority=5)
    entries_svc.assign(admin_user, a, MON, "AM", coil, published=True)
    run_fill(admin_user, MON, FRI)
    assert RotaEntry.objects.filter(session_type=coil).count() == 1  # quota met


def test_month_window_rule_skips_out_of_window(admin_user):
    PracticeSettings.load()
    pmc = make_session_type("PMC - Routine")
    a = make_clinician("Alice Adams")
    make_pattern(a)
    CoverageRule.objects.create(
        session_type=pmc, unit=CoverageRule.Unit.PER_DAY,
        months="10,11,12,1,2,3,4", priority=5)
    run_fill(admin_user, MON, FRI)  # July: out of window
    assert not RotaEntry.objects.filter(session_type=pmc).exists()
    jan_mon = date(2026, 1, 5)
    run_fill(admin_user, jan_mon, jan_mon + timedelta(days=4))
    assert RotaEntry.objects.filter(session_type=pmc).count() == 10


def test_blocks_same_day_excludes_from_duty(admin_user):
    PracticeSettings.load()
    pmc = make_session_type("PMC - Routine")
    duty = make_session_type("Duty", fairness_tracked=True)
    pmc.blocks_same_day.add(duty)
    a, b = _pool("Alice Adams", "Beth Brown")
    CoverageRule.objects.create(session_type=pmc,
                                unit=CoverageRule.Unit.PER_SESSION,
                                parts="AM", weekdays="0", priority=1)
    CoverageRule.objects.create(session_type=duty,
                                unit=CoverageRule.Unit.PER_DAY, weekdays="0",
                                priority=2)
    run_fill(admin_user, MON, MON)
    pmc_holder = RotaEntry.objects.get(session_type=pmc).clinician
    duty_holders = set(RotaEntry.objects.filter(session_type=duty)
                       .values_list("clinician", flat=True))
    assert pmc_holder.id not in duty_holders
    assert duty_holders  # duty still placed, on the other clinician


def test_default_site_stamped(admin_user):
    from rota.models import Site
    PracticeSettings.load()
    site = Site.objects.create(name="PMC")
    pmc = make_session_type("PMC - Urgent")
    pmc.default_site = site
    pmc.save()
    a = make_clinician("Alice Adams")
    make_pattern(a)
    CoverageRule.objects.create(session_type=pmc,
                                unit=CoverageRule.Unit.PER_DAY,
                                weekdays="0", priority=1)
    run_fill(admin_user, MON, MON)
    assert all(e.site == site
               for e in RotaEntry.objects.filter(session_type=pmc))


def test_pool_scoped_fair_shares():
    from rota.services import fairness
    from tests.factories import make_entry
    vas = make_session_type("Vas Clinic", fairness_tracked=True)
    a, b, outsider = _pool("Alice Adams", "Beth Brown", "Carl Cole")
    vas.allowed_clinicians.add(a, b)
    make_entry(a, day=MON, part="AM", session_type=vas)
    make_entry(b, day=MON, part="PM", session_type=vas)
    shares = fairness.fair_shares(vas, MON, MON + timedelta(days=6))
    assert set(shares) == {a.id, b.id}          # outsider not in the table
    assert shares[a.id].share == pytest.approx(1.0)  # 2 sessions / equal weights
