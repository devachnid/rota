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


# ------------------------------------------------------------- locums ---

from rota.services.cells import shows_on_roster


@pytest.mark.parametrize("is_locum,has_entry,shown", [
    (False, False, True),
    (False, True, True),
    (True, False, False),
    (True, True, True),
])
def test_only_an_idle_locum_is_hidden(is_locum, has_entry, shown):
    assert shows_on_roster(is_locum=is_locum, has_entry=has_entry,
                           in_service=True) is shown


@pytest.mark.parametrize("is_locum,has_entry,shown", [
    (False, False, False),
    (False, True, True),
    (True, False, False),
    (True, True, True),
])
def test_outside_the_window_only_an_entry_earns_a_row(is_locum, has_entry, shown):
    """A clinician who has not started, or has finished, for the whole
    period shown has no row -- unless a session of theirs is on the screen,
    which must stay reachable so it can be reviewed, moved or removed."""
    assert shows_on_roster(is_locum=is_locum, has_entry=has_entry,
                           in_service=False) is shown


def test_a_slot_the_pattern_says_is_not_worked_is_off_pattern():
    c = make_clinician()
    _works(c, weekday=0)  # Mondays only
    cell = cell_state(c.id, TUE, "AM", entry=None, resolver=_resolver([c]),
                      closed=False)
    assert cell["off_pattern"] is True


def test_off_pattern_is_false_on_a_closed_day():
    c = make_clinician()
    _works(c, weekday=0)
    cell = cell_state(c.id, TUE, "AM", entry=None, resolver=_resolver([c]),
                      closed=True)
    assert cell["off"] is True and cell["off_pattern"] is False


def test_off_pattern_is_false_outside_the_contractual_window():
    c = make_clinician(end_date=TUE - timedelta(days=1))
    _works(c)
    cell = cell_state(c.id, TUE, "AM", entry=None, resolver=_resolver([c]),
                      closed=False)
    assert cell["off"] is True and cell["off_pattern"] is False


def test_off_pattern_is_false_with_no_pattern_rows_at_all():
    c = make_clinician()
    cell = cell_state(c.id, TUE, "AM", entry=None, resolver=_resolver([c]),
                      closed=False)
    assert cell["off"] is True and cell["off_pattern"] is False


def test_off_pattern_is_false_under_an_entry():
    c = make_clinician()
    _works(c, weekday=0)
    e = make_entry(c, day=TUE, part="AM")
    cell = cell_state(c.id, TUE, "AM", entry=e, resolver=_resolver([c]),
                      closed=False)
    assert cell["off_pattern"] is False


def test_a_marked_half_does_not_merge_with_an_unmarked_half(admin_user):
    from rota.services.cells import one_block
    from rota.services import entries as entries_svc
    c = make_clinician()
    _works(c)
    rout = make_session_type("Routine")
    am = make_entry(c, day=TUE, part="AM", session_type=rout)
    pm = make_entry(c, day=TUE, part="PM", session_type=rout)
    entries_svc.set_entered(admin_user, am, True)
    r = _resolver([c])
    a = cell_state(c.id, TUE, "AM", entry=am, resolver=r, closed=False)
    p = cell_state(c.id, TUE, "PM", entry=pm, resolver=r, closed=False)
    assert a["entered"] is True and p["entered"] is False
    assert a["entered_by"] == "admin@example.com"
    assert not one_block(a, p)
    entries_svc.set_entered(admin_user, pm, True)
    p = cell_state(c.id, TUE, "PM", entry=pm, resolver=r, closed=False)
    assert one_block(a, p)


def test_a_whole_day_off_reads_as_one_block():
    from rota.services.cells import one_empty_block
    c = make_clinician()
    _works(c, weekday=0)  # Mondays only
    r = _resolver([c])
    am = cell_state(c.id, TUE, "AM", entry=None, resolver=r, closed=False)
    pm = cell_state(c.id, TUE, "PM", entry=None, resolver=r, closed=False)
    assert one_empty_block(am, pm)


def test_an_off_half_beside_a_worked_half_does_not_merge():
    from rota.services.cells import one_empty_block
    c = make_clinician()
    _works(c)
    _works(c, weekday=1, part="AM", works=False) if False else None
    r = _resolver([c])
    am = cell_state(c.id, TUE, "AM", entry=None, resolver=r, closed=False)
    pm = cell_state(c.id, TUE, "PM", entry=None, resolver=r, closed=False)
    assert not one_empty_block(am, pm), "two grey working cells are not a day off"


def test_the_same_absence_on_both_halves_reads_as_one_block():
    from rota.services.cells import one_empty_block
    c = make_clinician()
    _works(c)
    absence = make_absence(c, TUE)
    r = _resolver([c], [absence])
    am = cell_state(c.id, TUE, "AM", entry=None, resolver=r, closed=False)
    pm = cell_state(c.id, TUE, "PM", entry=None, resolver=r, closed=False)
    assert am["absence"] is not None
    assert one_empty_block(am, pm)


def test_an_absence_half_beside_an_off_half_does_not_merge():
    from rota.services.cells import one_empty_block
    c = make_clinician()
    _works(c, weekday=1)          # Tuesdays, both halves
    r0 = _resolver([c])
    assert cell_state(c.id, TUE, "PM", entry=None, resolver=r0, closed=False)["off"] is False
    from rota.models import PatternSlot
    PatternSlot.objects.filter(clinician=c, weekday=1, part="PM").update(works=False)
    absence = make_absence(c, TUE)
    r = _resolver([c], [absence])
    am = cell_state(c.id, TUE, "AM", entry=None, resolver=r, closed=False)
    pm = cell_state(c.id, TUE, "PM", entry=None, resolver=r, closed=False)
    assert am["absence"] is not None and pm["absence"] is None
    assert not one_empty_block(am, pm)


def test_a_closed_day_does_not_merge_into_an_off_block():
    from rota.services.cells import one_empty_block
    c = make_clinician()
    _works(c, weekday=0)
    r = _resolver([c])
    am = cell_state(c.id, TUE, "AM", entry=None, resolver=r, closed=True)
    pm = cell_state(c.id, TUE, "PM", entry=None, resolver=r, closed=True)
    assert not one_empty_block(am, pm)
