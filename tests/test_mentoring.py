from datetime import timedelta

import pytest

from rota.models import PracticeSettings, RotaEntry
from rota.services import entries as entries_svc
from rota.services import swaps as swaps_svc
from rota.services.fill import run_fill
from tests.factories import (MON, make_clinician, make_pattern,
                             make_session_type, make_trainee)

pytestmark = pytest.mark.django_db
FRI = MON + timedelta(days=4)
BACKLOG_START = MON - timedelta(weeks=12)


def _setup(trainer_days=(0, 1, 2, 3, 4)):
    s = PracticeSettings.load()
    ment = make_session_type("Mentoring", category="NON_CLINICAL")
    s.mentoring_session_type = ment
    s.save()
    trainer = make_clinician("Rita Trainer", is_trainer=True)
    make_pattern(trainer, weekdays=trainer_days)
    trainee = make_clinician("Terry Trainee")
    make_pattern(trainee)
    profile = make_trainee(clinician=trainee, stage="ST2", start=MON,
                           trainer=trainer)
    return ment, trainer, trainee, profile


def test_mentoring_pairs_trainee_with_fixed_trainer(admin_user):
    ment, trainer, trainee, _ = _setup()
    run_fill(admin_user, MON, FRI)
    entries = list(RotaEntry.objects.filter(session_type=ment))
    assert len(entries) == 2
    assert {e.clinician_id for e in entries} == {trainer.id, trainee.id}
    assert entries[0].day == entries[1].day and entries[0].part == entries[1].part
    groups = {e.companion_group for e in entries}
    assert len(groups) == 1 and None not in groups


def test_substitute_trainer_when_fixed_on_leave(admin_user):
    ment, trainer, trainee, _ = _setup()
    sub = make_clinician("Sam Substitute", is_trainer=True)
    make_pattern(sub)
    leave = make_session_type("Annual leave", category="ABSENCE")
    for d in range(5):
        for p in ("AM", "PM"):
            entries_svc.assign(admin_user, trainer, MON + timedelta(days=d),
                               p, leave, published=True)
    run_fill(admin_user, MON, FRI)
    mentors = set(RotaEntry.objects.filter(session_type=ment)
                  .values_list("clinician", flat=True))
    assert trainer.id not in mentors and sub.id in mentors


def test_no_trainer_reports_unfilled(admin_user):
    s = PracticeSettings.load()
    ment = make_session_type("Mentoring", category="NON_CLINICAL")
    s.mentoring_session_type = ment
    s.save()
    trainee = make_clinician("Terry Trainee")
    make_pattern(trainee)
    make_trainee(clinician=trainee, stage="ST2", start=MON, trainer=None)
    result = run_fill(admin_user, MON, FRI)
    assert not RotaEntry.objects.filter(session_type=ment).exists()
    assert any(u.session_type == "Mentoring" for u in result.unfilled)


def test_clear_cascades_to_companion(admin_user):
    ment, trainer, trainee, _ = _setup()
    run_fill(admin_user, MON, FRI)
    e = RotaEntry.objects.filter(session_type=ment).first()
    entries_svc.clear(admin_user, e.clinician, e.day, e.part)
    assert not RotaEntry.objects.filter(session_type=ment).exists()


def test_overwrite_unlinks_companion(admin_user):
    ment, trainer, trainee, _ = _setup()
    run_fill(admin_user, MON, FRI)
    e = RotaEntry.objects.filter(session_type=ment, clinician=trainee).get()
    entries_svc.assign(admin_user, trainee, e.day, e.part,
                       make_session_type("Routine"))
    partner = RotaEntry.objects.get(session_type=ment)
    assert partner.companion_group is None


def test_swap_rejects_paired_entries(admin_user):
    from rota.models import SwapRequest
    ment, trainer, trainee, _ = _setup()
    other = make_clinician("Olly Other")
    make_pattern(other)
    run_fill(admin_user, MON, FRI)
    e = RotaEntry.objects.filter(session_type=ment, clinician=trainee).get()
    entries_svc.assign(admin_user, other, e.day, e.part,
                       make_session_type("Routine"))
    req = SwapRequest.objects.create(
        proposer=trainee, proposer_day=e.day, proposer_part=e.part,
        colleague=other, colleague_day=e.day, colleague_part=e.part)
    assert any("paired session" in p for p in swaps_svc.validate(req))


def test_mentoring_backlog_reports_each_shortfall(admin_user):
    from rota.models import PatternSlot
    ment, trainer, trainee, profile = _setup(trainer_days=(0,))
    # Trainee works only Monday AM; trainer only Mondays. One candidate session
    # per week. Owed sessions are capped per week (Finding A2) at
    # ceil(rate)+1, so bump the rate (via wte) to 3/week -> cap 4, to still
    # exercise per-shortfall reporting with only 1 session available.
    PatternSlot.objects.filter(clinician=trainee).delete()
    make_pattern(trainee, weekdays=(0,), parts=("AM",))
    profile.placement_start = MON - timedelta(days=14)
    profile.wte_percent = 300
    profile.save()
    result = run_fill(admin_user, MON, MON + timedelta(days=4))
    placed = RotaEntry.objects.filter(session_type=ment).count()
    shortfalls = [u for u in result.unfilled if u.session_type == "Mentoring"]
    assert placed == 2, f"expected one pair (2 entries), got {placed}"
    assert len(shortfalls) == 3, (
        f"expected 3 mentoring shortfalls, got {len(shortfalls)}: "
        f"{[u.reason for u in shortfalls]}")


def test_post_leave_mentoring_does_not_pair_out_whole_week(admin_user):
    # Finding A2 reproduction: a trainee whose placement began 12 weeks ago
    # with no prior history (fresh install, no requirements_tracked_from)
    # has a large cumulative "due". Both trainee and trainer work full
    # weeks (10 sessions each). Without the per-week cap, every session
    # that week would become mentoring, pairing the trainer out entirely.
    ment, trainer, trainee, profile = _setup()  # full week for both
    profile.placement_start = BACKLOG_START
    profile.save()
    run_fill(admin_user, MON, FRI)
    trainer_entries = RotaEntry.objects.filter(clinician=trainer, session_type=ment)
    trainee_entries = RotaEntry.objects.filter(clinician=trainee, session_type=ment)
    # rate=1/week -> cap is ceil(1)+1 = 2, not the ~13-session backlog and
    # not all 10 of the trainer's available sessions.
    assert trainer_entries.count() == 2, (
        f"trainer should not be paired out of their whole week, "
        f"got {trainer_entries.count()} mentoring sessions")
    assert trainee_entries.count() == 2


def test_refill_overlapping_window_no_duplicate_mentoring_pair(admin_user):
    # Finding B: a published mentoring pair inside the fill window must be
    # counted as "done", or re-filling an overlapping window pairs the
    # trainee (and trainer) again for a duplicate session.
    ment, trainer, trainee, _ = _setup()
    week1_end = FRI
    run_fill(admin_user, MON, week1_end)
    entries_svc.publish_range(admin_user, MON, week1_end)
    assert RotaEntry.objects.filter(session_type=ment).count() == 2  # one pair

    week2_end = MON + timedelta(days=11)
    result = run_fill(admin_user, MON, week2_end)

    # Week 1's pair is untouched: no duplicate pair.
    assert RotaEntry.objects.filter(session_type=ment, day__lte=week1_end).count() == 2
    # Week 2 gets its own pair.
    assert RotaEntry.objects.filter(session_type=ment).count() == 4
    assert not any(u.session_type == "Mentoring" and u.day <= week1_end
                   for u in result.unfilled)
