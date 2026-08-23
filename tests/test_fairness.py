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


def test_pool_scoped_fair_shares_ignore_outsider_actuals():
    vas = make_session_type("Vas Clinic", fairness_tracked=True)
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    make_pattern(a)                 # 10 sessions/week -> equal weight
    make_pattern(b)                 # 10 sessions/week -> equal weight
    vas.allowed_clinicians.add(a, b)
    outsider = make_clinician("Carl Cole")
    make_pattern(outsider)
    make_entry(a, day=MON, part="AM", session_type=vas)
    # An out-of-pool clinician holding a session of this fairness-tracked
    # type (manual assignment, or later dropped from the pool) must not
    # inflate the pool's total_assigned numerator.
    make_entry(outsider, day=MON, part="PM", session_type=vas)
    shares = fairness.fair_shares(vas, MON, MON + timedelta(days=6))
    assert set(shares) == {a.id, b.id}
    # total_assigned should be 1 (a's session only), so with equal weights
    # each pool member's share is 0.5, not 1.0 (which the outsider's extra
    # session would produce if counted in the numerator).
    assert shares[a.id].share == pytest.approx(0.5)
    assert shares[b.id].share == pytest.approx(0.5)


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
