"""Read-only report on pattern damage.

The editor bug overwrote rows in place, so the original values are gone — there
is nothing to recover and any "repair" would be inventing data. This shows the
damage so it can be re-entered by hand through the fixed editor.
"""

from datetime import date, timedelta
from io import StringIO

import pytest
from django.core.management import call_command

from rota.models import PatternSlot
from tests.factories import make_clinician


def _run():
    out = StringIO()
    call_command("pattern_report", stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_it_lists_each_clinician_and_their_effective_dates():
    c = make_clinician("Historied", initials="HI")
    for eff in (date(2025, 1, 1), date(2025, 6, 1)):
        PatternSlot.objects.create(clinician=c, weekday=0, part="AM",
                                   works=True, effective_from=eff)
    output = _run()
    assert "Historied" in output
    assert "2025-01-01" in output
    assert "2025-06-01" in output


@pytest.mark.django_db
def test_a_single_date_history_is_flagged():
    """Every row at one date is what the overwrite bug leaves behind."""
    c = make_clinician("Flat", initials="FL")
    for part in ("AM", "PM"):
        PatternSlot.objects.create(clinician=c, weekday=0, part=part,
                                   works=True, effective_from=date(2025, 1, 1))
    assert "single date" in _run().lower()


@pytest.mark.django_db
def test_rows_dated_today_are_flagged():
    c = make_clinician("Todayed", initials="TD")
    PatternSlot.objects.create(clinician=c, weekday=0, part="AM",
                               works=True, effective_from=date.today())
    assert "today" in _run().lower()


@pytest.mark.django_db
def test_a_clinician_with_no_pattern_is_reported_not_skipped():
    """They cannot be scheduled and leave will not materialise for them —
    that is worth seeing."""
    make_clinician("Empty", initials="EM")
    assert "Empty" in _run()
    assert "no pattern" in _run().lower()


@pytest.mark.django_db
def test_it_changes_nothing():
    c = make_clinician("Untouched", initials="UT")
    PatternSlot.objects.create(clinician=c, weekday=0, part="AM",
                               works=True, effective_from=date(2025, 1, 1))
    before = list(PatternSlot.objects.values_list("pk", "works", "effective_from"))
    _run()
    assert list(
        PatternSlot.objects.values_list("pk", "works", "effective_from")) == before
