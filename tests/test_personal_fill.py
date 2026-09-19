"""The personal-requirement pass: when a clinician is due, one session of
the type in that week's cheapest free candidate; nothing before it is
due; at most one per clinician per week; a miss is reported and rolls
into the next week."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from rota.models import CoverageRule, PracticeSettings, RotaEntry
from rota.services.fill import run_fill
from tests.factories import (MON, make_clinician, make_entry, make_pattern,
                             make_requirement, make_session_type)

pytestmark = pytest.mark.django_db
TUE, WED, THU, FRI = (MON + timedelta(days=i) for i in range(1, 5))
NEXT = MON + timedelta(days=7)


def _gp(name="Ann Able", **pattern):
    c = make_clinician(name)
    make_pattern(c, **pattern)
    return c


def _placed(nh):
    return list(RotaEntry.objects.filter(session_type=nh, manually_set=False)
                .order_by("day", "part").values_list("day", "part"))


def test_a_clinician_with_none_yet_is_placed_in_the_first_live_week(admin_user):
    PracticeSettings.load()
    c = _gp()
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c], active_from=MON)
    result = run_fill(admin_user, MON, FRI)
    assert _placed(nh) == [(MON, "AM")]
    e = RotaEntry.objects.get(session_type=nh)
    assert e.fill_reason == "personal requirement" and not e.manually_set and not e.is_published
    assert result.created == 1 and result.unfilled == []


def test_not_due_yet_means_nothing_placed(admin_user):
    PracticeSettings.load()
    c = _gp()
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c], interval_weeks=6)
    make_entry(c, day=MON - timedelta(days=21), session_type=nh)
    run_fill(admin_user, MON, FRI)
    assert _placed(nh) == []


def test_a_session_this_pass_places_moves_the_clock_forward(admin_user):
    """interval 2, three weeks, none yet: week 1 gets one, week 2 is not
    due, week 3 is due again — two placements, never two in a row."""
    PracticeSettings.load()
    c = _gp()
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c], interval_weeks=2, active_from=MON)
    result = run_fill(admin_user, MON, MON + timedelta(days=20))
    assert _placed(nh) == [(MON, "AM"), (MON + timedelta(days=14), "AM")]
    assert not [u for u in result.unfilled if u.session_type == nh.name]


def test_nothing_is_due_after_the_requirement_ends(admin_user):
    PracticeSettings.load()
    c = _gp()
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c], interval_weeks=1, active_from=MON,
                     active_until=MON + timedelta(days=4))
    result = run_fill(admin_user, MON, MON + timedelta(days=18))
    assert _placed(nh) == [(MON, "AM")]
    assert not [u for u in result.unfilled if u.session_type == nh.name], (
        "weeks after active_until are not due, so they are not misses")


def test_seven_weeks_since_the_last_one_is_placed_in_the_first_week(admin_user):
    PracticeSettings.load()
    c = _gp()
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c], interval_weeks=6)
    make_entry(c, day=MON - timedelta(days=49), session_type=nh)
    run_fill(admin_user, MON, FRI)
    assert _placed(nh) == [(MON, "AM")]


def test_a_hand_placed_session_in_the_window_resets_the_clock(admin_user):
    PracticeSettings.load()
    c = _gp()
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c], interval_weeks=2)
    make_entry(c, day=WED, session_type=nh)          # by hand, week 1
    run_fill(admin_user, MON, NEXT + timedelta(days=4))  # two weeks
    assert _placed(nh) == [], "week 1 is done by hand and week 2 is not yet due"


def test_no_free_session_is_reported_and_tried_again_next_week(admin_user):
    PracticeSettings.load()
    c = _gp(weekdays=(0,), parts=("AM",))          # Monday mornings only
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c])
    make_entry(c, day=MON, part="AM", session_type=make_session_type("Routine"))
    result = run_fill(admin_user, MON, NEXT + timedelta(days=4))
    assert _placed(nh) == [(NEXT, "AM")]
    misses = [u for u in result.unfilled if u.session_type == nh.name]
    assert [(u.day, u.part, u.reason) for u in misses] == [(MON, None, "no free session")]


def test_part_and_weekdays_restrict_the_candidates(admin_user):
    PracticeSettings.load()
    c = _gp()
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c], part="PM", weekdays="3")
    run_fill(admin_user, MON, FRI)
    assert _placed(nh) == [(THU, "PM")]


def test_the_cheapest_session_wins(admin_user):
    """Where the most other people are available and free — the session
    that can best spare one, as SDL already chooses."""
    PracticeSettings.load()
    c = _gp()
    for name in ("Bob Baker", "Cal Cole"):
        _gp(name, weekdays=(2,))                    # Wednesdays only
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c])
    run_fill(admin_user, MON, FRI)
    assert _placed(nh) == [(WED, "AM")]


def test_a_same_day_block_is_honoured(admin_user):
    PracticeSettings.load()
    c = _gp()
    nh = make_session_type("Nursing home round", code="NH")
    duty = make_session_type("Duty", code="DUTY")
    duty.blocks_same_day.add(nh)
    make_entry(c, day=MON, part="AM", session_type=duty)
    make_requirement(nh, [c])
    run_fill(admin_user, MON, FRI)
    assert _placed(nh) == [(TUE, "AM")]


def test_coverage_rules_take_people_first(admin_user):
    PracticeSettings.load()
    c = _gp(weekdays=(0,), parts=("AM",))
    duty = make_session_type("Duty", code="DUTY")
    CoverageRule.objects.create(session_type=duty, parts="AM", weekdays="0", priority=1)
    nh = make_session_type("Nursing home round", code="NH")
    make_requirement(nh, [c])
    result = run_fill(admin_user, MON, FRI)
    assert RotaEntry.objects.filter(session_type=duty, day=MON, part="AM").exists()
    assert _placed(nh) == []
    assert any(u.session_type == nh.name and u.reason == "no free session"
               for u in result.unfilled)


def test_an_ineligible_clinician_is_skipped_not_placed(admin_user):
    from tests.factories import make_group
    PracticeSettings.load()
    partners = make_group("Partner", display_order=1)
    c = _gp()                                       # not a partner
    nh = make_session_type("Nursing home round", code="NH")
    nh.allowed_groups.add(partners)
    make_requirement(nh, [c])
    result = run_fill(admin_user, MON, FRI)
    assert _placed(nh) == []
    assert any(u.reason == "no free session" for u in result.unfilled)


def test_the_pass_has_no_n_plus_one(admin_user):
    PracticeSettings.load()
    nh = make_session_type("Nursing home round", code="NH")
    people = [_gp(n) for n in ("Ann Able", "Bob Baker", "Cal Cole", "Dan Dee")]
    make_requirement(nh, people)
    with CaptureQueriesContext(connection) as four:
        run_fill(admin_user, MON, FRI)
    RotaEntry.objects.all().delete()
    more = [_gp(n) for n in ("Eve East", "Fay Fern", "Gus Gale", "Hal Hart")]
    make_requirement(make_session_type("Coil clinic", code="COIL"), more)
    with CaptureQueriesContext(connection) as eight:
        run_fill(admin_user, MON, FRI)
    selects = lambda ctx: [q["sql"] for q in ctx.captured_queries  # noqa: E731
                           if q["sql"].lstrip().upper().startswith("SELECT")
                           and "rota_rotaentry" in q["sql"]
                           and "MAX(" in q["sql"].upper()]
    assert len(selects(eight)) == 2 and len(selects(four)) == 1, (
        "one last-done query per requirement, none per clinician or week")
