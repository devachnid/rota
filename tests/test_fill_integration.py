from datetime import timedelta

import pytest

from rota.models import CoverageRule, PracticeSettings, RotaEntry
from rota.services.fill import run_fill
from tests.factories import (MON, make_clinician, make_commitment, make_entry,
                             make_pattern, make_session_type, make_trainee)

pytestmark = pytest.mark.django_db
FRI = MON + timedelta(days=4)


def test_v1_shaped_data_unchanged(admin_user):
    """No v2 config -> the fairness pick still follows v1's weighted-share
    rule, matching v1's test_part_timer_gets_weighted_share for Alice/Beth.

    This is also the sole guard on "the pool-scoped fairness denominator
    change didn't break weighting", so it must fail under an unweighted
    round-robin, not just a weighted one. Carl Cole (8 sessions/week --
    double Beth's 4) is pre-seeded with MORE actual duty sessions than Beth
    (2 vs 1), so a naive "fewest done first" round-robin would pick Beth for
    Monday. The weighted engine must instead pick Carl: his fair *share* of
    what's already assigned, scaled by his higher weight, outstrips what
    he's done by more than Beth's does -- i.e. weight, not raw session
    count, decides the Monday and Wednesday picks below.
    """
    PracticeSettings.load()
    duty = make_session_type("Duty", fairness_tracked=True)
    CoverageRule.objects.create(session_type=duty,
                                unit=CoverageRule.Unit.PER_DAY, priority=1)
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    make_pattern(a)                      # 10 sessions/week
    make_pattern(b, weekdays=(0, 1))     # 4 sessions/week, Mon+Tue only
    c = make_clinician("Carl Cole")
    make_pattern(c, weekdays=(0, 1, 2, 3))  # 8 sessions/week, Mon-Thu

    # Pre-existing duty history (within the 91-day fairness lookback):
    # Alice 3 sessions, Beth 1, Carl 2 -- Beth has done the fewest.
    make_entry(a, day=MON - timedelta(days=21), part="AM", session_type=duty)
    make_entry(a, day=MON - timedelta(days=21), part="PM", session_type=duty)
    make_entry(a, day=MON - timedelta(days=14), part="AM", session_type=duty)
    make_entry(b, day=MON - timedelta(days=14), part="PM", session_type=duty)
    make_entry(c, day=MON - timedelta(days=7), part="AM", session_type=duty)
    make_entry(c, day=MON - timedelta(days=7), part="PM", session_type=duty)

    run_fill(admin_user, MON, FRI)
    picks = {e.day: e.clinician.name
             for e in RotaEntry.objects.filter(session_type=duty, part="AM")}
    assert picks[MON] == "Carl Cole"                       # weight beats Beth's lower raw count
    assert picks[MON + timedelta(days=1)] == "Alice Adams"
    assert picks[MON + timedelta(days=2)] == "Carl Cole"
    assert picks[MON + timedelta(days=3)] == "Alice Adams"
    assert picks[MON + timedelta(days=4)] == "Alice Adams"


def test_full_pipeline_realistic_week(admin_user):
    s = PracticeSettings.load()
    vts = make_session_type("VTS", category="NON_CLINICAL")
    sdl = make_session_type("SDL", category="NON_CLINICAL")
    ment = make_session_type("Mentoring", category="NON_CLINICAL")
    routine = make_session_type("Routine")
    s.vts_session_type, s.sdl_session_type = vts, sdl
    s.mentoring_session_type = ment
    s.default_fill_session_type = routine
    s.save()

    duty = make_session_type("Duty", fairness_tracked=True)
    CoverageRule.objects.create(session_type=duty,
                                unit=CoverageRule.Unit.PER_DAY, priority=1)
    gps = [make_clinician(n) for n in
           ("Alice Adams", "Beth Brown", "Carl Cole", "Dana Dee")]
    for g in gps:
        make_pattern(g)
    gps[0].is_trainer = True
    gps[0].save()
    trainee = make_clinician("Terry Trainee")
    make_pattern(trainee)
    make_trainee(clinician=trainee, stage="ST2", start=MON, trainer=gps[0])
    make_commitment(gps[1], session_type=make_session_type("Vision"),
                    weekday=0, part="AM")

    result = run_fill(admin_user, MON, FRI, fill_default=True)

    assert RotaEntry.objects.filter(session_type__name="Vision",
                                    day=MON, part="AM").exists()
    assert RotaEntry.objects.filter(session_type=vts, part="AM",
                                    day=MON + timedelta(days=1)).exists()
    assert RotaEntry.objects.filter(session_type=duty).count() == 10
    ment_entries = RotaEntry.objects.filter(session_type=ment)
    assert ment_entries.count() == 2
    assert RotaEntry.objects.filter(session_type=sdl,
                                    clinician=trainee).count() == 1
    # Default fill must have run: every remaining working cell became Routine.
    assert RotaEntry.objects.filter(session_type=routine).exists()
    assert not RotaEntry.objects.filter(session_type=routine,
                                        fill_reason="").exists()
    # every working cell filled, all drafts carry reasons
    assert not result.unfilled
    assert all(e.fill_reason for e in RotaEntry.objects.filter(manually_set=False))
