"""A swap must not hand a session to someone Breathe says is off."""

from datetime import date

import pytest

from rota.models import SwapRequest
from rota.services import swaps
from tests.factories import make_absence, make_clinician, make_entry, make_pattern, make_session_type

pytestmark = pytest.mark.django_db

MON, TUE = date(2026, 9, 14), date(2026, 9, 15)


def _swap():
    a, b = make_clinician("Ann Able"), make_clinician("Bob Baker")
    make_pattern(a); make_pattern(b)
    rout = make_session_type("Routine", code="ROUT")
    make_entry(a, day=MON, part="AM", session_type=rout)
    make_entry(a, day=TUE, part="PM", session_type=rout)
    make_entry(b, day=MON, part="AM", session_type=rout)
    make_entry(b, day=TUE, part="PM", session_type=rout)
    req = SwapRequest.objects.create(proposer=a, proposer_day=MON, proposer_part="AM",
                                     colleague=b, colleague_day=TUE, colleague_part="PM")
    return a, b, req


def test_a_clean_swap_has_no_problems():
    _, _, req = _swap()
    assert swaps.validate(req) == []


def test_the_colleague_being_on_leave_for_the_session_they_would_receive_is_refused():
    a, b, req = _swap()
    make_absence(b, MON)  # Bob would receive Ann's Monday AM, and is off Monday
    problems = swaps.validate(req)
    assert any("Bob Baker is on leave on Mon 14 Sep AM" in p for p in problems)


def test_the_proposer_being_on_leave_for_the_session_they_would_receive_is_refused():
    a, b, req = _swap()
    make_absence(a, TUE, half_start=True, half_start_am_pm="PM")
    problems = swaps.validate(req)
    assert any("Ann Able is on leave on Tue 15 Sep PM" in p for p in problems)


def test_leave_on_the_other_half_of_the_day_does_not_block():
    a, b, req = _swap()
    make_absence(b, MON, half_start=True, half_start_am_pm="PM")  # off Monday PM; receives AM
    assert swaps.validate(req) == []


def test_leave_problems_come_after_the_existing_kinds():
    """The order is: a session that has gone, the pattern, paired sessions,
    then leave — and a leave problem is reported even when an earlier check
    has already failed, so the list is the whole picture."""
    a, b, req = _swap()
    from rota.models import RotaEntry
    RotaEntry.objects.filter(clinician=b).delete()  # Bob now has no session
    make_absence(a, TUE)
    problems = swaps.validate(req)
    assert "has no session" in problems[0]
    assert "is on leave" in problems[-1]
