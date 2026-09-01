"""The precedence every rota cell obeys, tested once rather than per screen.

    entry exists           -> the entry
    on leave and ghostable -> a ghosted leave chip
    works_on               -> off=False, nothing allocated
    otherwise              -> off=True

The two guards on "ghostable" are the subtle part and cost three review
rounds in the previous phase, so each gets its own test here.
"""

from datetime import date

import pytest

from rota.models import LeaveRequest, PatternSlot
from rota.services import availability
from rota.services.cells import cell_state
from tests.factories import make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db

TUE = date(2026, 9, 8)


def _resolver(clinicians, leave=()):
    rows = list(PatternSlot.objects.filter(clinician__in=clinicians))
    return availability.AvailabilityResolver(rows, list(clinicians), list(leave))


def _works(c, weekday=1):
    for part in ("AM", "PM"):
        PatternSlot.objects.create(clinician=c, weekday=weekday, part=part,
                                   works=True, effective_from=date(2020, 1, 1))


def test_an_entry_wins_over_everything():
    c = make_clinician()
    _works(c)
    e = make_entry(c, day=TUE, part="AM")
    cell = cell_state(c.id, TUE, "AM", entry=e, resolver=_resolver([c]),
                      closed=False)
    assert cell["entry"] is e
    assert cell["off"] is False
    assert cell["ghost_leave"] is None


def test_a_working_session_with_no_entry_is_not_off():
    c = make_clinician()
    _works(c)
    cell = cell_state(c.id, TUE, "AM", entry=None, resolver=_resolver([c]),
                      closed=False)
    assert cell["off"] is False
    assert cell["entry"] is None


def test_a_session_the_clinician_does_not_work_is_off():
    c = make_clinician()
    _works(c, weekday=0)  # Mondays only
    cell = cell_state(c.id, TUE, "AM", entry=None, resolver=_resolver([c]),
                      closed=False)
    assert cell["off"] is True


def test_approved_leave_with_no_entry_ghosts():
    c = make_clinician()
    _works(c)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    req = LeaveRequest.objects.create(
        clinician=c, session_type=al, start_date=TUE, end_date=TUE,
        status=LeaveRequest.Status.APPROVED)
    cell = cell_state(c.id, TUE, "AM", entry=None,
                      resolver=_resolver([c], [req]), closed=False)
    assert cell["ghost_leave"] == al


def test_a_ghost_is_suppressed_on_a_closed_day():
    """Approval writes nothing on a bank holiday, so a chip there accuses it
    of missing an entry it was right not to write."""
    c = make_clinician()
    _works(c)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    req = LeaveRequest.objects.create(
        clinician=c, session_type=al, start_date=TUE, end_date=TUE,
        status=LeaveRequest.Status.APPROVED)
    cell = cell_state(c.id, TUE, "AM", entry=None,
                      resolver=_resolver([c], [req]), closed=True)
    assert cell["ghost_leave"] is None


def test_a_ghost_is_suppressed_outside_the_contractual_window():
    """A clinician with no pattern rows still gets ghosts — but not across a
    week they are not employed for."""
    c = make_clinician(start_date=date(2026, 12, 1))  # starts long after TUE
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    req = LeaveRequest.objects.create(
        clinician=c, session_type=al, start_date=TUE, end_date=TUE,
        status=LeaveRequest.Status.APPROVED)
    cell = cell_state(c.id, TUE, "AM", entry=None,
                      resolver=_resolver([c], [req]), closed=False)
    assert cell["ghost_leave"] is None


def test_the_partner_is_carried_through():
    c = make_clinician()
    _works(c)
    cell = cell_state(c.id, TUE, "AM", entry=None, resolver=_resolver([c]),
                      closed=False, partner="Dr Trainer")
    assert cell["partner"] == "Dr Trainer"
