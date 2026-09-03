"""The precedence every rota cell obeys, tested once rather than per screen.

    entry exists           -> the entry
    on leave and showable  -> the Breathe absence
    works_on               -> off=False, nothing allocated
    otherwise              -> off=True

The two guards on "showable" are the subtle part and cost three review
rounds in the previous phase, so each gets its own test here.
"""

from datetime import date, timedelta

import pytest

from rota.models import BreatheLeaveMapping, PatternSlot
from rota.services import availability
from rota.services.cells import cell_state
from tests.factories import make_absence, make_clinician, make_entry, make_session_type

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


# ------------------------------------------------ leave under an entry ---
#
# A published week, then leave approved in Breathe: the entry still stands
# (an entry beats leave for what the cell SHOWS, by design) but the cell
# must know it is standing on leave, or nothing can mark it. `on_leave`
# used to be forced False whenever an entry existed. It is not any more.

from rota.services.cells import leave_label


def test_leave_label_per_kind():
    assert leave_label("holiday", "") == "Holiday"
    assert leave_label("holiday", "Annual") == "Holiday"
    assert leave_label("sickness", "") == "Sick"
    assert leave_label("other", "Jury service") == "Other leave: Jury service"
    assert leave_label("other", "") == "Other leave"
    assert leave_label("study", "") == "Study"


def test_covering_is_public_and_names_the_absence():
    c = make_clinician()
    _works(c)
    absences = [make_absence(c, TUE, kind="other", reason="Jury service")]
    r = _resolver([c], absences)
    assert r.covering(c.id, TUE, "AM") == ("other", "Jury service")
    assert r.covering(c.id, TUE + timedelta(days=1), "AM") is None
    assert not hasattr(r, "_covering"), "the private name was renamed, not duplicated"


def test_an_entry_over_breathe_leave_is_a_clash():
    c = make_clinician()
    _works(c)
    e = make_entry(c, day=TUE, part="AM")
    cell = cell_state(c.id, TUE, "AM", entry=e,
                      resolver=_resolver([c], [make_absence(c, TUE)]),
                      closed=False)
    assert cell["entry"] is e
    assert cell["on_leave"] is True
    assert cell["clash"] is True
    assert cell["leave_label"] == "Holiday"
    assert cell["absence"] is None, "the chip shown is still the entry's"


def test_an_absence_entry_over_breathe_leave_agrees_and_is_not_a_clash():
    """An admin marking someone AL by hand when Breathe also says off is
    agreement, not a rostered session on a day off."""
    c = make_clinician()
    _works(c)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    e = make_entry(c, day=TUE, part="AM", session_type=al)
    cell = cell_state(c.id, TUE, "AM", entry=e,
                      resolver=_resolver([c], [make_absence(c, TUE)]),
                      closed=False)
    assert cell["on_leave"] is True
    assert cell["clash"] is False
    assert cell["leave_label"] == "Holiday"


def test_an_entry_with_no_leave_is_not_a_clash():
    c = make_clinician()
    _works(c)
    e = make_entry(c, day=TUE, part="AM")
    cell = cell_state(c.id, TUE, "AM", entry=e, resolver=_resolver([c]),
                      closed=False)
    assert cell["on_leave"] is False
    assert cell["clash"] is False
    assert cell["leave_label"] is None


def test_leave_with_no_entry_labels_but_is_not_a_clash():
    c = make_clinician()
    _works(c)
    cell = cell_state(c.id, TUE, "AM", entry=None,
                      resolver=_resolver([c], [make_absence(c, TUE)]),
                      closed=False)
    assert cell["on_leave"] is True
    assert cell["clash"] is False
    assert cell["leave_label"] == "Holiday"
    assert cell["absence"] is not None


def test_an_unmapped_kind_still_labels():
    """The label never goes through the mapping. Deleting a mapping row
    empties the chip; it must not empty the tooltip or the warning."""
    BreatheLeaveMapping.objects.filter(kind="sickness").delete()
    c = make_clinician()
    _works(c)
    cell = cell_state(c.id, TUE, "AM", entry=None,
                      resolver=_resolver([c], [make_absence(c, TUE, kind="sickness")]),
                      closed=False)
    assert cell["absence"] is None
    assert cell["on_leave"] is True
    assert cell["leave_label"] == "Sick"


def test_a_clash_ignores_the_closed_flag():
    """An entry means someone is rostered, closed day or not."""
    c = make_clinician()
    _works(c)
    e = make_entry(c, day=TUE, part="AM")
    cell = cell_state(c.id, TUE, "AM", entry=e,
                      resolver=_resolver([c], [make_absence(c, TUE)]),
                      closed=True)
    assert cell["clash"] is True
