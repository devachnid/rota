from datetime import timedelta

import pytest

from rota.models import (CoverageRule, PracticeSettings, RotaEntry,
                         SessionType)
from rota.services.fill import run_fill
from tests.factories import (MON, make_clinician, make_commitment,
                             make_pattern, make_session_type, make_trainee)

pytestmark = pytest.mark.django_db
FRI = MON + timedelta(days=4)


def test_v1_shaped_data_unchanged(admin_user):
    """No v2 config -> byte-identical placement to the v1 engine."""
    PracticeSettings.load()
    duty = make_session_type("Duty", fairness_tracked=True)
    CoverageRule.objects.create(session_type=duty,
                                unit=CoverageRule.Unit.PER_DAY, priority=1)
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    make_pattern(a)
    make_pattern(b, weekdays=(0, 1))
    run_fill(admin_user, MON, FRI)
    picks = {e.day: e.clinician.name
             for e in RotaEntry.objects.filter(session_type=duty, part="AM")}
    # Same expectations as v1's test_part_timer_gets_weighted_share:
    assert picks[MON] == "Alice Adams"
    assert picks[MON + timedelta(days=1)] == "Beth Brown"
    assert all(picks[MON + timedelta(days=d)] == "Alice Adams"
               for d in (2, 3, 4))


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
    # every working cell filled, all drafts carry reasons
    assert not result.unfilled
    assert all(e.fill_reason for e in RotaEntry.objects.filter(manually_set=False))
