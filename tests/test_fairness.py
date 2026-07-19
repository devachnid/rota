from datetime import timedelta

import pytest

from rota.services import fairness
from tests.factories import (MON, make_clinician, make_entry, make_pattern,
                             make_session_type)

pytestmark = pytest.mark.django_db


@pytest.fixture
def duty(db):
    return make_session_type("Duty", fairness_tracked=True)


def test_counts_sessions_in_range(duty):
    c = make_clinician()
    make_entry(c, day=MON, part="AM", session_type=duty)
    make_entry(c, day=MON, part="PM", session_type=duty)
    make_entry(c, day=MON + timedelta(days=1), part="AM",
               session_type=make_session_type("Routine"))
    assert fairness.counts(duty, MON, MON + timedelta(days=6)) == {c.id: 2}


def test_weights_reflect_weekly_sessions(duty):
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    make_pattern(a)                                   # 10 sessions
    make_pattern(b, weekdays=(0, 1))                  # 4 sessions
    w = fairness.weights(MON)
    assert w[a.id] == 10 and w[b.id] == 4


def test_fair_shares_weighted(duty):
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    make_pattern(a)
    make_pattern(b, weekdays=(0, 1))
    for i in range(5):
        make_entry(a, day=MON + timedelta(days=i), part="AM", session_type=duty)
    for i in range(2):
        make_entry(b, day=MON + timedelta(days=i), part="PM", session_type=duty)
    shares = fairness.fair_shares(duty, MON, MON + timedelta(days=6))
    assert shares[a.id].actual == 5 and shares[b.id].actual == 2
    assert shares[a.id].share == pytest.approx(7 * 10 / 14)
    assert shares[b.id].share == pytest.approx(7 * 4 / 14)
    assert shares[a.id].balance == pytest.approx(5 - 5.0)
    assert shares[b.id].balance == pytest.approx(0.0)


def test_last_done(duty):
    a = make_clinician()
    make_entry(a, day=MON - timedelta(days=7), part="AM", session_type=duty)
    make_entry(a, day=MON - timedelta(days=3), part="AM", session_type=duty)
    assert fairness.last_done(duty, MON)[a.id] == MON - timedelta(days=3)


def test_counts_exclude_drafts_when_asked(duty):
    c = make_clinician()
    make_entry(c, day=MON, part="AM", session_type=duty, is_published=False)
    assert fairness.counts(duty, MON, MON, include_drafts=False) == {}
    assert fairness.counts(duty, MON, MON) == {c.id: 1}
