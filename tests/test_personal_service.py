"""The rolling clock: a clinician is due N weeks after their most recent
session of the type, however it got there; with none, from active_from.
Once due it stays due until one is placed."""

from datetime import date, timedelta

import pytest

from rota.services import personal
from tests.factories import MON, make_clinician, make_entry, make_requirement, make_session_type

pytestmark = pytest.mark.django_db
TUE = MON + timedelta(days=1)


def _setup():
    nh = make_session_type("Nursing home round", code="NH")
    a, b = make_clinician("Ann Able"), make_clinician("Bob Baker")
    return nh, a, b, make_requirement(nh, [a, b], interval_weeks=6, active_from=MON)


def test_last_done_is_per_clinician_and_respects_before_and_drafts():
    nh, a, b, req = _setup()
    make_entry(a, day=MON - timedelta(days=30), session_type=nh)
    make_entry(a, day=MON - timedelta(days=2), session_type=nh, is_published=False)
    make_entry(b, day=MON, session_type=nh)
    last = personal.last_done(req, [a.id, b.id], MON)
    assert last == {a.id: MON - timedelta(days=2), b.id: None}
    published = personal.last_done(req, [a.id, b.id], MON, include_drafts=False)
    assert published[a.id] == MON - timedelta(days=30)
    assert personal.last_done(req, [b.id], MON + timedelta(days=1))[b.id] == MON


def test_last_done_ignores_other_session_types():
    nh, a, b, req = _setup()
    make_entry(a, day=MON - timedelta(days=2), session_type=make_session_type("Routine"))
    assert personal.last_done(req, [a.id], MON)[a.id] is None


def test_due_from_the_last_one_or_from_active_from():
    nh, a, b, req = _setup()
    assert personal.due_monday(req, None) == MON
    assert personal.due_monday(req, TUE) == MON + timedelta(days=42)
    assert personal.due_monday(req, MON + timedelta(days=41)) == MON + timedelta(days=35 + 42)


def test_status_across_a_year_boundary():
    nh, a, b, req = _setup()
    today = date(2027, 1, 4)  # a Monday
    s = personal.status_from(req, date(2026, 11, 10), today)
    assert s.due == date(2026, 12, 21) and s.weeks_overdue == 2
    assert s.label == "2 weeks overdue"
    assert personal.status_from(req, date(2026, 11, 24), today).label == "due this week"
    assert personal.status_from(req, date(2026, 12, 1), today).label == "on track"
    assert personal.status_from(req, date(2026, 11, 17), today).label == "1 week overdue"


def test_status_queries_the_clinicians_last_including_today():
    nh, a, b, req = _setup()
    make_entry(a, day=MON, session_type=nh)
    s = personal.status(req, a.id, MON)
    assert s.last == MON and s.due == MON + timedelta(days=42) and s.label == "on track"
    assert personal.status(req, b.id, MON).label == "due this week"


def test_live_requirements_and_overdue_count():
    nh, a, b, req = _setup()
    make_requirement(make_session_type("Later", code="LT"), [a], active_from=MON + timedelta(days=7))
    make_clinician("Gone Away", active=False).personal_requirements.add(req)
    live = list(personal.live_requirements(MON))
    assert live == [req]
    assert [c.name for c in live[0].clinicians.all()] == ["Ann Able", "Bob Baker"]
    assert personal.overdue_count(MON) == 0             # both due this week, not overdue
    assert personal.overdue_count(MON + timedelta(days=7)) == 2
    make_entry(a, day=MON + timedelta(days=3), session_type=nh)
    assert personal.overdue_count(MON + timedelta(days=7)) == 1


def test_overdue_count_is_two_queries_per_requirement(django_assert_max_num_queries):
    nh, a, b, req = _setup()
    with django_assert_max_num_queries(3):
        personal.overdue_count(MON + timedelta(days=7))
