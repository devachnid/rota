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
def test_a_clinician_whose_pattern_was_set_once_and_never_revised_is_not_flagged():
    """The normal healthy state for a stable rota. Flagging it was the bug:
    a report that flags most of the practice teaches its reader to skip it."""
    c = make_clinician("Steady", initials="SD")
    for part in ("AM", "PM"):
        PatternSlot.objects.create(clinician=c, weekday=0, part=part,
                                   works=True, effective_from=date(2025, 1, 1))
    out = _run()
    assert "Steady" in out, "every clinician's history is still printed"
    assert "suspect" not in out.lower()


@pytest.mark.django_db
def test_a_date_that_turns_sessions_off_is_surfaced():
    """The shape an overwrite leaves on the sessions it displaced. A
    deliberate reduction looks identical, so this is a place to look."""
    c = make_clinician("Reduced", initials="RD")
    PatternSlot.objects.create(clinician=c, weekday=0, part="AM",
                               works=True, effective_from=date(2025, 1, 1))
    PatternSlot.objects.create(clinician=c, weekday=0, part="AM",
                               works=False, effective_from=date(2025, 6, 1))
    assert "2025-06-01" in _run()


@pytest.mark.django_db
def test_rows_dated_today_are_shown_but_not_flagged():
    """The old code called every row dated today "suspect"; a routine save
    made today looks exactly like a bug replaying today's date, so the fix
    demotes it to plain context shown inline, not a signal that feeds the
    closing tally."""
    c = make_clinician("Todayed", initials="TD")
    PatternSlot.objects.create(clinician=c, weekday=0, part="AM",
                               works=True, effective_from=date.today())
    out = _run()
    assert "<- today" in out, "the plain inline marker should still be there"
    assert "place to look" not in out.lower(), (
        "a today-dated row with no reduction must not feed the signal tally")


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
