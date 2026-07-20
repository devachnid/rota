from datetime import timedelta

import pytest

from rota.models import PatternSlot
from rota.services.patterns import bulk_set_pattern, current_pattern
from tests.factories import MON, make_clinician, make_pattern

pytestmark = pytest.mark.django_db


def test_current_pattern_empty_for_no_rows():
    c = make_clinician()
    assert current_pattern(c, MON) == {}


def test_current_pattern_reflects_latest_effective_row():
    c = make_clinician()
    make_pattern(c, weekdays=(0,), parts=("AM",), works=True,
                 effective_from=MON - timedelta(days=365))
    make_pattern(c, weekdays=(0,), parts=("AM",), works=False,
                 effective_from=MON)
    assert current_pattern(c, MON - timedelta(days=1)) == {(0, "AM"): True}
    assert current_pattern(c, MON) == {(0, "AM"): False}


def test_bulk_set_pattern_creates_only_changed_cells():
    c = make_clinician()
    make_pattern(c, weekdays=(0, 1, 2, 3, 4), parts=("AM", "PM"),
                 effective_from=MON - timedelta(days=365))
    desired = {(w, p): True for w in (0, 1, 2, 3, 4) for p in ("AM", "PM")}
    desired[(1, "PM")] = False  # Tuesday PM: change from True to False
    desired[(5, "AM")] = True  # Saturday AM: change from (absent=False) to True

    changed = bulk_set_pattern(c, MON, desired)

    assert changed == 2
    at_mon = PatternSlot.objects.filter(clinician=c, effective_from=MON)
    assert at_mon.count() == 2
    assert at_mon.get(weekday=1, part="PM").works is False
    assert at_mon.get(weekday=5, part="AM").works is True
    assert PatternSlot.objects.filter(
        clinician=c, effective_from=MON - timedelta(days=365)
    ).count() == 10


def test_bulk_set_pattern_from_scratch():
    c = make_clinician()
    desired = {(0, "AM"): True, (0, "PM"): True, (2, "AM"): True}
    changed = bulk_set_pattern(c, MON, desired)
    assert changed == 3
    assert PatternSlot.objects.filter(clinician=c, effective_from=MON).count() == 3


def test_bulk_set_pattern_resave_same_date_updates_in_place():
    c = make_clinician()
    bulk_set_pattern(c, MON, {(0, "AM"): True})
    changed = bulk_set_pattern(c, MON, {(0, "AM"): False})
    assert changed == 1
    rows = PatternSlot.objects.filter(clinician=c, weekday=0, part="AM",
                                      effective_from=MON)
    assert rows.count() == 1
    assert rows.get().works is False


def test_bulk_set_pattern_noop_when_nothing_changes():
    c = make_clinician()
    make_pattern(c, weekdays=(0,), parts=("AM",),
                 effective_from=MON - timedelta(days=365))
    changed = bulk_set_pattern(c, MON, {(0, "AM"): True})
    assert changed == 0
    assert not PatternSlot.objects.filter(clinician=c, effective_from=MON).exists()
