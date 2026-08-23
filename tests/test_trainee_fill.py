from datetime import timedelta

import pytest

from rota.models import PracticeSettings, RotaEntry
from rota.services import entries as entries_svc
from rota.services.fill import run_fill
from rota.services.fill.trainees import _anchor
from tests.factories import (MON, make_clinician, make_pattern,
                             make_session_type, make_trainee)

pytestmark = pytest.mark.django_db
TUE = MON + timedelta(days=1)
BACKLOG_START = MON - timedelta(weeks=12)


def _setup_vts():
    s = PracticeSettings.load()
    vts = make_session_type("VTS", category="NON_CLINICAL")
    s.vts_session_type = vts
    s.save()
    return vts


def test_st2_vts_lands_tuesday_am(admin_user):
    vts = _setup_vts()
    c = make_clinician("Terry Trainee")
    make_pattern(c)
    make_trainee(clinician=c, stage="ST2", start=MON)
    run_fill(admin_user, MON, MON + timedelta(days=4))
    e = RotaEntry.objects.get(session_type=vts)
    assert (e.day, e.part, e.clinician_id) == (TUE, "AM", c.id)


def test_st3_vts_lands_tuesday_pm(admin_user):
    vts = _setup_vts()
    c = make_clinician("Terry Trainee")
    make_pattern(c)
    make_trainee(clinician=c, stage="ST3", start=MON)
    run_fill(admin_user, MON, MON + timedelta(days=4))
    e = RotaEntry.objects.get(session_type=vts)
    assert (e.day, e.part) == (TUE, "PM")


def test_half_wte_vts_alternates_weeks(admin_user):
    vts = _setup_vts()
    c = make_clinician("Terry Trainee")
    make_pattern(c)
    make_trainee(clinician=c, stage="ST2", wte=50, start=MON)
    run_fill(admin_user, MON, MON + timedelta(days=27))  # 4 weeks
    days = sorted(RotaEntry.objects.filter(session_type=vts)
                  .values_list("day", flat=True))
    assert days == [TUE + timedelta(days=7), TUE + timedelta(days=21)]  # wks 2,4


def test_vts_blocked_slot_reports_unfilled(admin_user):
    vts = _setup_vts()
    c = make_clinician("Terry Trainee")
    make_pattern(c)
    make_trainee(clinician=c, stage="ST2", start=MON)
    leave = make_session_type("Annual leave", category="ABSENCE")
    entries_svc.assign(admin_user, c, TUE, "AM", leave, published=True)
    result = run_fill(admin_user, MON, MON + timedelta(days=4))
    assert not RotaEntry.objects.filter(session_type=vts).exists()
    assert any(u.session_type == "VTS" for u in result.unfilled)


def test_deleted_stage_rule_skips_trainee_without_crashing(admin_user):
    from rota.models import TraineeStageRule
    vts = _setup_vts()
    c = make_clinician("Terry Trainee")
    make_pattern(c)
    make_trainee(clinician=c, stage="ST2", start=MON)
    TraineeStageRule.objects.filter(stage="ST2").delete()
    # Must not raise, and must place nothing for the now-rateless trainee.
    result = run_fill(admin_user, MON, MON + timedelta(days=4))
    assert not RotaEntry.objects.filter(session_type=vts).exists()
    assert not any(u.session_type == "VTS" for u in result.unfilled)


def test_fy2_gets_no_vts(admin_user):
    vts = _setup_vts()
    c = make_clinician("Freya FY2")
    make_pattern(c)
    make_trainee(clinician=c, stage="FY2", start=MON)
    run_fill(admin_user, MON, MON + timedelta(days=4))
    assert not RotaEntry.objects.filter(session_type=vts).exists()


def test_no_vts_type_configured_is_noop(admin_user):
    PracticeSettings.load()
    c = make_clinician("Terry Trainee")
    make_pattern(c)
    make_trainee(clinician=c, stage="ST2", start=MON)
    run_fill(admin_user, MON, MON + timedelta(days=4))  # must not crash
    assert not RotaEntry.objects.exclude(session_type__name="Routine").exists()


def _setup_sdl():
    s = PracticeSettings.load()
    sdl = make_session_type("SDL", category="NON_CLINICAL")
    s.sdl_session_type = sdl
    s.save()
    return sdl


def test_sdl_placed_where_cover_is_thickest(admin_user):
    sdl = _setup_sdl()
    t = make_clinician("Terry Trainee")
    make_pattern(t)
    make_trainee(clinician=t, stage="FY2", wte=50, start=MON)  # 1 SDL/wk at 50%...
    # FY2 at 50% -> 2 * 0.5 = 1 SDL/week due from week 1?  due_through(1.0, w1)=1: yes.
    # Cover: three colleagues work Thursday only -> Thursday sessions score highest.
    for name in ("Alice Adams", "Beth Brown", "Carl Cole"):
        make_pattern(make_clinician(name), weekdays=(3,))
    run_fill(admin_user, MON, MON + timedelta(days=4))
    e = RotaEntry.objects.get(session_type=sdl)
    assert e.day == MON + timedelta(days=3)  # Thursday


def test_fy2_full_time_gets_two_sdl_per_week(admin_user):
    sdl = _setup_sdl()
    t = make_clinician("Freya FY2")
    make_pattern(t)
    make_trainee(clinician=t, stage="FY2", wte=100, start=MON)
    run_fill(admin_user, MON, MON + timedelta(days=4))
    assert RotaEntry.objects.filter(session_type=sdl).count() == 2


def test_sdl_avoids_vts_anchor_slot(admin_user):
    vts = _setup_vts()
    sdl = _setup_sdl()
    t = make_clinician("Terry Trainee")
    make_pattern(t, weekdays=(1,))  # Tuesday only: VTS takes AM
    make_trainee(clinician=t, stage="ST2", start=MON)
    run_fill(admin_user, MON, MON + timedelta(days=4))
    assert RotaEntry.objects.get(session_type=vts).part == "AM"
    assert RotaEntry.objects.get(session_type=sdl).part == "PM"


def test_sdl_partial_shortfall_reported(admin_user):
    sdl = _setup_sdl()
    t = make_clinician("Freya FY2")
    # Works only Monday AM: one candidate session, but FY2 full-time needs 2/wk
    make_pattern(t, weekdays=(0,), parts=("AM",))
    make_trainee(clinician=t, stage="FY2", wte=100, start=MON)
    result = run_fill(admin_user, MON, MON + timedelta(days=4))
    assert RotaEntry.objects.filter(session_type=sdl).count() == 1
    shortfalls = [u for u in result.unfilled if u.session_type == "SDL"]
    assert len(shortfalls) == 1, f"expected 1 SDL shortfall, got {len(shortfalls)}"


# --- Finding A: unbounded trainee catch-up -------------------------------

def test_anchor_uses_requirements_tracked_from_when_set():
    profile = make_trainee(clinician=make_clinician("Terry Trainee"),
                           stage="ST2", start=BACKLOG_START,
                           requirements_tracked_from=MON)
    assert _anchor(profile) == MON


def test_anchor_defaults_to_placement_start_when_unset():
    profile = make_trainee(clinician=make_clinician("Terry Trainee"),
                           stage="ST2", start=BACKLOG_START)
    assert _anchor(profile) == BACKLOG_START


def test_fresh_install_sdl_places_normal_entitlement_not_burst(admin_user):
    # Placement began 12 weeks ago but the rota system has only just started
    # tracking it (requirements_tracked_from = this fill window's Monday).
    # Without A1, cumulative "due" since placement_start would be ~26
    # sessions against done=0, bursting to fill every available slot.
    sdl = _setup_sdl()
    t = make_clinician("Freya FY2")
    make_pattern(t)  # full week, 10 sessions available
    make_trainee(clinician=t, stage="FY2", wte=100, start=BACKLOG_START,
                requirements_tracked_from=MON)
    run_fill(admin_user, MON, MON + timedelta(days=4))
    # FY2 full-time entitlement is 2 SDL/week - exactly that, not a burst
    # that consumes all 10 available sessions.
    assert RotaEntry.objects.filter(session_type=sdl).count() == 2


def test_backlog_sdl_capped_leaves_free_cells(admin_user):
    # Genuine backlog (no requirements_tracked_from): cumulative due is
    # large, but a single week must only place ceil(rate)+1 sessions, not
    # the whole backlog in one burst.
    sdl = _setup_sdl()
    t = make_clinician("Freya FY2")
    make_pattern(t)  # full week, 10 sessions available
    make_trainee(clinician=t, stage="FY2", wte=100, start=BACKLOG_START)
    run_fill(admin_user, MON, MON + timedelta(days=4))
    placed = RotaEntry.objects.filter(session_type=sdl).count()
    # rate=2/week -> cap is ceil(2)+1 = 3, not the ~26-session backlog and
    # not the full 10 available slots either.
    assert placed == 3, f"expected capped placement of 3, got {placed}"
    assert placed < 10, "trainee should still have free cells left that week"


def test_refill_overlapping_window_no_duplicates_or_spurious_unfilled(admin_user):
    # Finding B: entries already published inside the fill window must be
    # counted as "done", or a re-fill of an overlapping window duplicates
    # them and reports spurious shortfalls for weeks already delivered.
    vts = _setup_vts()
    sdl = _setup_sdl()
    t = make_clinician("Terry Trainee")
    make_pattern(t)
    make_trainee(clinician=t, stage="ST2", start=MON)  # 1 VTS/wk, 1 SDL/wk
    week1_end = MON + timedelta(days=4)

    run_fill(admin_user, MON, week1_end)
    entries_svc.publish_range(admin_user, MON, week1_end)
    assert RotaEntry.objects.filter(session_type=vts).count() == 1
    assert RotaEntry.objects.filter(session_type=sdl).count() == 1

    week2_end = MON + timedelta(days=11)
    result = run_fill(admin_user, MON, week2_end)

    # Week 1 is untouched: no duplicate entries.
    assert RotaEntry.objects.filter(session_type=vts, day__lte=week1_end).count() == 1
    assert RotaEntry.objects.filter(session_type=sdl, day__lte=week1_end).count() == 1
    # Week 2 gets its own entitlement.
    assert RotaEntry.objects.filter(session_type=vts).count() == 2
    assert RotaEntry.objects.filter(session_type=sdl).count() == 2
    # No spurious unfilled reports for the already-delivered week.
    assert not any(u.session_type in ("VTS", "SDL") and u.day <= week1_end
                   for u in result.unfilled)
