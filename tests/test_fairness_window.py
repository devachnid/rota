"""Fairness must ask the same availability question as everything else.

`weekly_sessions()` and the fairness pool selected on `active` alone — the one
consumer the AvailabilityResolver consolidation never reached. `active` and the
contractual window sit side by side precisely so a leaver can be dated out
without anyone remembering to untick a box, and until this the two disagreed:
a clinician past their `end_date` but still flagged active kept full weight.

Two consequences, both real. The fairness report gave them a share they can
never work and a balance sinking further every week; and `coverage._pick`'s
denominator — `_pool_total_weight`, summed from these same weights — counted
clinicians who can never be candidates, diluting every real candidate's share.
"""

from datetime import timedelta

import pytest

from rota.services import availability, fairness
from tests.factories import (MON, make_clinician, make_entry, make_pattern,
                             make_session_type)

pytestmark = pytest.mark.django_db

END = MON + timedelta(days=6)


@pytest.fixture
def duty(db):
    return make_session_type("Duty", fairness_tracked=True)


def test_a_clinician_past_their_end_date_carries_no_weight(duty):
    here = make_clinician("Ann Active")
    gone = make_clinician("Bea Bygone", end_date=MON - timedelta(days=1))
    make_pattern(here)
    make_pattern(gone)

    w = fairness.weights(END)
    assert w[here.id] == 10
    assert w.get(gone.id, 0) == 0, (
        "a clinician who left before this week still carries fairness weight"
    )


def test_a_clinician_past_their_end_date_is_excluded_from_fair_shares(duty):
    here = make_clinician("Ann Active")
    gone = make_clinician("Bea Bygone", end_date=MON - timedelta(days=1))
    make_pattern(here)
    make_pattern(gone)
    make_entry(here, day=MON, part="AM", session_type=duty)

    shares = fairness.fair_shares(duty, MON, END)
    assert set(shares) == {here.id}, (
        "a leaver appears in the fairness table with a share they can never "
        "work and a balance that sinks every week"
    )
    # The whole assignment belongs to the one clinician who can work it, so
    # their share is the whole of it — not half, diluted by a phantom.
    assert shares[here.id].share == pytest.approx(1.0)
    assert shares[here.id].balance == pytest.approx(0.0)


def test_a_clinician_who_has_not_started_yet_is_excluded_too(duty):
    """The other end of the same window. end_date is the case the review
    reproduced; start_date reaches it by the identical route."""
    here = make_clinician("Ann Active")
    joiner = make_clinician("Cal Coming", start_date=END + timedelta(days=1))
    make_pattern(here)
    make_pattern(joiner)
    make_entry(here, day=MON, part="AM", session_type=duty)

    assert fairness.weights(END).get(joiner.id, 0) == 0
    assert set(fairness.fair_shares(duty, MON, END)) == {here.id}


def test_a_clinician_inside_their_window_is_unaffected(duty):
    """The dates are not a way to drop someone quietly: bounds that contain
    the anchor date must change nothing at all."""
    bounded = make_clinician("Dee Dated",
                             start_date=MON - timedelta(days=365),
                             end_date=END + timedelta(days=365))
    unbounded = make_clinician("Eve Endless")
    make_pattern(bounded)
    make_pattern(unbounded)
    for i in range(2):
        make_entry(bounded, day=MON + timedelta(days=i), part="AM",
                   session_type=duty)

    w = fairness.weights(END)
    assert w[bounded.id] == 10 and w[unbounded.id] == 10

    shares = fairness.fair_shares(duty, MON, END)
    assert set(shares) == {bounded.id, unbounded.id}
    assert shares[bounded.id].share == pytest.approx(1.0)
    assert shares[unbounded.id].share == pytest.approx(1.0)


def test_weekly_sessions_is_zero_outside_the_window_and_when_inactive():
    """The count itself, not just the callers — every future consumer of
    weekly_sessions() inherits this rather than having to remember it."""
    c = make_clinician("Fay Former")
    make_pattern(c)
    assert availability.weekly_sessions(c, MON) == 10

    c.end_date = MON - timedelta(days=1)
    assert availability.weekly_sessions(c, MON) == 0
    assert availability.weekly_sessions(c, MON - timedelta(days=1)) == 10, (
        "the window is read at the date asked about, not at today"
    )

    c.end_date = None
    c.active = False
    assert availability.weekly_sessions(c, MON) == 0


def test_the_fill_engines_weights_lose_the_leaver_too(duty):
    """FillContext caches fairness.weights(end) and coverage._pick divides by
    the sum of them over the eligible pool. A phantom in the denominator
    shrinks every real candidate's share of the same total."""
    from rota.services.fill.context import FillContext

    here = make_clinician("Ann Active")
    gone = make_clinician("Bea Bygone", end_date=MON - timedelta(days=1))
    make_pattern(here)
    make_pattern(gone)

    ctx = FillContext(MON, END)
    assert ctx.weights.get(gone.id, 0) == 0
    assert ctx.weights[here.id] == 10
    assert not any(ctx.available(gone.id, MON + timedelta(days=i), part)
                   for i in range(5) for part in ("AM", "PM")), (
        "a clinician with no weight must also be no candidate — otherwise "
        "the pick would divide by a weight of zero"
    )


def test_the_fairness_report_renders_without_the_leaver(admin_client, duty):
    """report_fairness indexes its own active-clinician map by the ids
    fair_shares returns. Narrowing the pool must not leave that lookup
    holding an id it does not have."""
    here = make_clinician("Ann Active")
    gone = make_clinician("Bea Bygone", end_date=MON - timedelta(days=1))
    make_pattern(here)
    make_pattern(gone)
    make_entry(here, day=MON, part="AM", session_type=duty)
    make_entry(gone, day=MON, part="PM", session_type=duty)

    resp = admin_client.get(
        f"/reports/fairness/?start={MON.isoformat()}&end={END.isoformat()}")
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Ann Active" in html
    assert "Bea Bygone" not in html
