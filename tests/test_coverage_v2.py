from datetime import date, timedelta

import pytest

from rota.models import CoverageRule, PracticeSettings, RotaEntry, Site
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


def test_quota_spills_onto_remaining_weekdays_when_preferred_cant_absorb(admin_user):
    PracticeSettings.load()
    vas = make_session_type("Vas Clinic", fairness_tracked=True)
    pool = _pool("Alice Adams", "Beth Brown", "Carl Cole")
    vas.allowed_clinicians.add(*pool)
    # Only 2 preferred weekdays (Thu, Tue) but count=6 needs 3 full days
    # (6 sessions) this week — more than the preferred days alone (4
    # sessions) can absorb, so the third full day must spill onto the
    # earliest remaining allowed weekday (Monday) rather than the rule
    # stopping short at 4 sessions placed.
    CoverageRule.objects.create(
        session_type=vas, unit=CoverageRule.Unit.FULL_DAY_PREFERRED,
        frequency=CoverageRule.Frequency.PER_WEEK, count=6,
        weekdays="0,1,2,3,4", preferred_weekdays="3,1", priority=5)
    run_fill(admin_user, MON, FRI)
    entries = RotaEntry.objects.filter(session_type=vas)
    assert entries.count() == 6, "expected 3 full days (6 sessions) placed"
    tue = MON + timedelta(days=1)
    thu = MON + timedelta(days=3)
    assert set(entries.values_list("day", flat=True)) == {MON, tue, thu}


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
    a = make_clinician("Alice Adams")
    make_pattern(a)
    CoverageRule.objects.create(session_type=pmc,
                                unit=CoverageRule.Unit.PER_SESSION,
                                parts="AM", weekdays="0", priority=1)
    CoverageRule.objects.create(session_type=duty,
                                unit=CoverageRule.Unit.PER_SESSION,
                                parts="PM", weekdays="0", priority=2)
    result = run_fill(admin_user, MON, MON)
    # Alice takes the AM PMC session; her PM cell is free, so only
    # blocks_same_day can stop her also taking the PM duty.
    assert RotaEntry.objects.get(session_type=pmc).clinician_id == a.id
    assert not RotaEntry.objects.filter(session_type=duty).exists()
    assert any(u.session_type == "Duty" for u in result.unfilled)


def test_blocking_is_directional(admin_user):
    """Holding PMC blocks Duty; holding Duty does NOT block PMC."""
    PracticeSettings.load()
    pmc = make_session_type("PMC - Routine")
    duty = make_session_type("Duty", fairness_tracked=True)
    pmc.blocks_same_day.add(duty)
    a = make_clinician("Alice Adams")
    make_pattern(a)
    # Duty first (priority 1) this time, PMC second.
    CoverageRule.objects.create(session_type=duty,
                                unit=CoverageRule.Unit.PER_SESSION,
                                parts="AM", weekdays="0", priority=1)
    CoverageRule.objects.create(session_type=pmc,
                                unit=CoverageRule.Unit.PER_SESSION,
                                parts="PM", weekdays="0", priority=2)
    run_fill(admin_user, MON, MON)
    # Alice holds Duty AM; PMC does not appear in Duty's block list, so
    # she can still take PMC in the PM.
    assert RotaEntry.objects.get(session_type=duty).clinician_id == a.id
    assert RotaEntry.objects.get(session_type=pmc).clinician_id == a.id


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


def test_fill_engine_seed_state_ignores_outsider_actuals(admin_user):
    from tests.factories import make_entry
    PracticeSettings.load()
    vas = make_session_type("Vas Clinic", fairness_tracked=True)
    a, b = _pool("Alice Adams", "Beth Brown")
    vas.allowed_clinicians.add(a, b)
    outsider = make_clinician("Carl Cole")
    make_pattern(outsider)
    # An out-of-pool clinician's prior session (within the fairness
    # lookback window) must not be counted in the pool's total_assigned
    # numerator when the engine seeds fairness state at pass start.
    make_entry(outsider, day=MON - timedelta(days=7), part="AM",
               session_type=vas)
    CoverageRule.objects.create(
        session_type=vas, unit=CoverageRule.Unit.PER_SESSION,
        parts="AM", weekdays="0", priority=5)
    run_fill(admin_user, MON, MON)
    entry = RotaEntry.objects.get(session_type=vas, day=MON, part="AM")
    assert "fair share 0.0, done 0" in entry.fill_reason
    assert entry.clinician_id == a.id


def test_half_covered_full_day_tops_up_missing_part_only(admin_user):
    from tests.factories import make_entry
    PracticeSettings.load()
    duty = make_session_type("Duty", fairness_tracked=True)
    a, b = _pool("Alice Adams", "Beth Brown")
    duty.allowed_clinicians.add(a, b)
    # A manual half-day: Alice already has Monday AM duty, PM is empty.
    make_entry(a, day=MON, part="AM", session_type=duty)
    CoverageRule.objects.create(
        session_type=duty, unit=CoverageRule.Unit.PER_DAY,
        weekdays="0", priority=5)  # count defaults to 1 full day
    run_fill(admin_user, MON, MON)
    am = RotaEntry.objects.filter(session_type=duty, day=MON, part="AM")
    pm = RotaEntry.objects.filter(session_type=duty, day=MON, part="PM")
    # Exactly one PM session gets added (whoever fairness picks); AM must
    # keep its single existing holder, not gain a second one from a
    # full-day top-up stacked on top of the already-covered part.
    assert am.count() == 1
    assert am.first().clinician_id == a.id
    assert pm.count() == 1


def test_fairness_seed_counts_duty_already_in_fill_window(admin_user):
    from tests.factories import make_entry
    PracticeSettings.load()
    duty = make_session_type("Duty", fairness_tracked=True)
    a, b = _pool("Alice Adams", "Beth Brown")  # equal weights, "Alice" sorts first
    duty.allowed_clinicians.add(a, b)
    # Alice already has two manually-placed published Duty sessions inside
    # the fill window itself (not the pre-window lookback) — on different
    # days from the one the rule below will fill, so they don't collide.
    make_entry(a, day=MON, part="AM", session_type=duty)
    make_entry(a, day=MON + timedelta(days=1), part="AM", session_type=duty)
    wed = MON + timedelta(days=2)
    CoverageRule.objects.create(
        session_type=duty, unit=CoverageRule.Unit.PER_SESSION,
        parts="AM", weekdays="2", priority=5)  # Wednesday only
    run_fill(admin_user, MON, FRI)
    entry = RotaEntry.objects.get(session_type=duty, day=wed, part="AM")
    # Without seeding actuals from Alice's in-window duty, both candidates
    # would tie on deficit=0 and the alphabetical tie-break would still
    # hand it to Alice despite her already being the busier of the two.
    assert entry.clinician_id == b.id


def test_fairness_state_last_stays_monotonic_within_a_week():
    # Quota rules evaluate preferred_weekdays first, so a clinician can be
    # placed on a chronologically-later day (e.g. Thursday) before an
    # earlier day in the same week (e.g. Tuesday) is even considered. If
    # that same clinician is then picked again for the earlier day,
    # record() must not let `last` regress backwards — that would make
    # them look longer-overdue than they really are for the rest of the
    # week's tie-breaks.
    from rota.services.fill.coverage import _FairnessState
    thu = MON + timedelta(days=3)
    tue = MON + timedelta(days=1)
    state = _FairnessState(actuals={}, last={}, total_assigned=0, total_weight=1)
    state.record(1, thu, 1)  # preferred (later) day processed first
    assert state.last[1] == thu
    state.record(1, tue, 1)  # earlier day in the same week, same clinician
    assert state.last[1] == thu, "last must not regress to an earlier day"
    # actuals/total_assigned bookkeeping is unaffected by the last-field fix
    assert state.actuals[1] == 2
    assert state.total_assigned == 2


def test_eligible_ids_excludes_inactive_individually_allowed_clinician():
    from rota.services.fill.context import FillContext
    vas = make_session_type("Vas Clinic", fairness_tracked=True)
    active = make_clinician("Alice Adams")
    make_pattern(active)
    inactive = make_clinician("Ines Inactive", active=False)
    vas.allowed_clinicians.add(active, inactive)
    ctx = FillContext(MON, MON + timedelta(days=6))
    # The inactive clinician still has an allowed_clinicians M2M row, but
    # eligible_ids() must not offer them up as a candidate for this
    # restricted type — only the group-membership half of the M2M was
    # previously filtered to active, leaving this a latent trap.
    assert ctx.eligible_ids(vas) == {active.id}


def test_eligible_ids_restricted_solely_to_deactivated_clinician_is_empty():
    from rota.services.fill.context import FillContext
    vas = make_session_type("Vas Clinic", fairness_tracked=True)
    other_active = make_clinician("Alice Adams")
    make_pattern(other_active)
    inactive = make_clinician("Ines Inactive", active=False)
    vas.allowed_clinicians.add(inactive)
    ctx = FillContext(MON, MON + timedelta(days=6))
    # vas has an allowed_clinicians row, so it IS restricted — but that
    # row's only clinician has since gone inactive. The pool must end up
    # empty, not silently fall back to "unrestricted" (which would wrongly
    # offer up other_active, who was never granted access to this type).
    assert ctx.eligible_ids(vas) == set()


def test_default_fill_stamps_site(admin_user):
    s = PracticeSettings.load()
    site = Site.objects.create(name="Main Surgery")
    routine = make_session_type("Routine")
    routine.default_site = site
    routine.save()
    s.default_fill_session_type = routine
    s.save()
    a = make_clinician("Alice Adams")
    make_pattern(a, weekdays=(0,), parts=("AM",))
    run_fill(admin_user, MON, MON, fill_default=True)
    entry = RotaEntry.objects.get(clinician=a, day=MON, part="AM")
    assert entry.session_type == routine
    assert entry.site == site
