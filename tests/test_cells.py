"""The precedence every rota cell obeys, tested once rather than per screen.

    entry exists           -> the entry
    on leave and showable  -> the Breathe absence
    works_on               -> off=False, nothing allocated
    otherwise              -> off=True

The two guards on "showable" are the subtle part and cost three review
rounds in the previous phase, so each gets its own test here.
"""

from datetime import date

import pytest

from rota.models import BreatheLeaveMapping, PatternSlot
from rota.services import availability
from rota.services.cells import cell_state
from tests.factories import make_absence, make_clinician, make_entry

pytestmark = pytest.mark.django_db

TUE = date(2026, 9, 8)


def _resolver(clinicians, absences=()):
    rows = list(PatternSlot.objects.filter(clinician__in=clinicians))
    return availability.AvailabilityResolver(
        rows, list(clinicians), list(absences), BreatheLeaveMapping.as_dict())


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
    assert cell["absence"] is None


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
    absence = make_absence(c, TUE)
    cell = cell_state(c.id, TUE, "AM", entry=None,
                      resolver=_resolver([c], [absence]), closed=False)
    assert cell["absence"].code == "AL"


def test_a_ghost_is_suppressed_on_a_closed_day():
    """Approval writes nothing on a bank holiday, so a chip there accuses it
    of missing an entry it was right not to write."""
    c = make_clinician()
    _works(c)
    absence = make_absence(c, TUE)
    cell = cell_state(c.id, TUE, "AM", entry=None,
                      resolver=_resolver([c], [absence]), closed=True)
    assert cell["absence"] is None


def test_a_ghost_is_suppressed_outside_the_contractual_window():
    """A clinician with no pattern rows still gets chips — but not across a
    week they are not employed for."""
    c = make_clinician(start_date=date(2026, 12, 1))  # starts long after TUE
    absence = make_absence(c, TUE)
    cell = cell_state(c.id, TUE, "AM", entry=None,
                      resolver=_resolver([c], [absence]), closed=False)
    assert cell["absence"] is None


def test_the_partner_is_carried_through():
    c = make_clinician()
    _works(c)
    cell = cell_state(c.id, TUE, "AM", entry=None, resolver=_resolver([c]),
                      closed=False, partner="Dr Trainer")
    assert cell["partner"] == "Dr Trainer"
