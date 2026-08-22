from datetime import timedelta

import pytest

from rota.models import PracticeSettings, RotaEntry
from rota.services import entries as entries_svc
from rota.services.fill import run_fill
from tests.factories import (MON, make_clinician, make_pattern,
                             make_session_type, make_trainee)

pytestmark = pytest.mark.django_db
TUE = MON + timedelta(days=1)


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
