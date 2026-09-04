"""One answer to "can this clinician be given this session?".

Before this, the question was answered in the grid and in the fill engine
separately, and knew only about the working pattern. Clinician date windows
and Breathe absences both belong in it. Composing them in one place is what
stops `active` and the dates disagreeing.
"""

from datetime import date, timedelta

import pytest

from rota.models import BreatheAbsence, BreatheLeaveMapping, PatternSlot
from rota.services import availability
from rota.services.availability import AvailabilityResolver
from tests.factories import make_absence, make_clinician, make_pattern

MON = date(2026, 9, 7)
LONG_AGO = date(2025, 1, 1)


def _pattern(clinician, weekday, part, works=True, effective_from=LONG_AGO):
    return PatternSlot.objects.create(
        clinician=clinician, weekday=weekday, part=part,
        works=works, effective_from=effective_from)


def _resolver(clinicians, rows=(), absences=()):
    return AvailabilityResolver(
        list(rows), list(clinicians), list(absences), BreatheLeaveMapping.as_dict())


@pytest.mark.django_db
def test_works_on_follows_the_pattern():
    c = make_clinician("Pat", initials="PA")
    rows = [_pattern(c, 0, "AM")]
    r = _resolver([c], rows)
    assert r.works_on(c.id, MON, "AM") is True
    assert r.works_on(c.id, MON, "PM") is False


@pytest.mark.django_db
def test_an_inactive_clinician_never_works():
    c = make_clinician("Gone", initials="GO")
    rows = [_pattern(c, 0, "AM")]
    c.active = False
    assert _resolver([c], rows).works_on(c.id, MON, "AM") is False


@pytest.mark.django_db
def test_a_session_before_the_start_date_is_not_worked():
    c = make_clinician("Starts", initials="SS")
    rows = [_pattern(c, 0, "AM")]
    c.start_date = MON + timedelta(days=7)
    assert _resolver([c], rows).works_on(c.id, MON, "AM") is False
    assert _resolver([c], rows).works_on(c.id, MON + timedelta(days=7), "AM") is True


@pytest.mark.django_db
def test_a_session_after_the_end_date_is_not_worked():
    c = make_clinician("Ends", initials="EN")
    rows = [_pattern(c, 0, "AM")]
    c.end_date = MON - timedelta(days=1)
    assert _resolver([c], rows).works_on(c.id, MON, "AM") is False


@pytest.mark.django_db
def test_leave_type_returns_the_session_type_for_rendering():
    c = make_clinician("Chip", initials="CH")
    absence = make_absence(c, MON)
    r = _resolver([c], (), [absence])
    assert r.leave_type(c.id, MON, "AM").code == "AL"
    assert r.leave_type(c.id, MON + timedelta(days=1), "AM") is None


@pytest.mark.django_db
def test_has_pattern_distinguishes_no_rows_from_not_working():
    with_rows = make_clinician("Has", initials="HS")
    without = make_clinician("Hasnt", initials="HN")
    rows = [_pattern(with_rows, 0, "AM")]
    r = _resolver([with_rows, without], rows)
    assert r.has_pattern(with_rows.id) is True
    assert r.has_pattern(without.id) is False


@pytest.mark.django_db
def test_the_resolver_issues_no_queries_once_built():
    """Both callers ask it once per cell. A query here is a query per cell."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    c = make_clinician("Quiet", initials="QT")
    rows = [_pattern(c, 0, "AM")]
    r = _resolver([c], rows)
    with CaptureQueriesContext(connection) as ctx:
        for _ in range(20):
            r.available(c.id, MON, "AM")
    assert len(ctx) == 0


@pytest.mark.django_db
def test_module_works_on_respects_active_and_the_date_window():
    """leave.sessions_affected() calls this function, not the resolver — the
    two implement the same rule separately, so the resolver's tests prove
    nothing here."""
    from rota.services.availability import works_on

    c = make_clinician("Module", initials="MD")
    _pattern(c, 0, "AM")
    assert works_on(c, MON, "AM") is True

    c.active = False
    c.save()
    assert works_on(c, MON, "AM") is False, "an inactive clinician still works"

    c.active = True
    c.end_date = MON - timedelta(days=1)
    c.save()
    assert works_on(c, MON, "AM") is False, "a session after end_date still works"

    c.end_date = None
    c.start_date = MON + timedelta(days=1)
    c.save()
    assert works_on(c, MON, "AM") is False, "a session before start_date still works"


@pytest.mark.django_db
def test_leave_type_covers_the_full_multi_day_range_but_not_beyond_it():
    """Every other leave test uses a single-day absence, so start <= day <=
    end could quietly be < at either end and still pass."""
    c = make_clinician("Spanning", initials="SP")
    absence = make_absence(c, MON, MON + timedelta(days=2))
    r = _resolver([c], (), [absence])

    assert r.leave_type(c.id, MON, "AM").code == "AL", "first day of the range"
    assert r.leave_type(c.id, MON + timedelta(days=1), "AM").code == "AL", "middle of the range"
    assert r.leave_type(c.id, MON + timedelta(days=2), "AM").code == "AL", "last day of the range"
    assert r.leave_type(c.id, MON - timedelta(days=1), "AM") is None, "day before the range"
    assert r.leave_type(c.id, MON + timedelta(days=3), "AM") is None, "day after the range"


@pytest.mark.django_db
def test_has_pattern_is_true_even_when_the_only_row_says_not_working():
    """has_pattern's whole point is telling "no rows at all" apart from "has
    rows but doesn't work this session" — a regression filtering
    _with_pattern to works=True rows would pass the original test."""
    c = make_clinician("Never", initials="NV")
    rows = [_pattern(c, 0, "AM", works=False)]
    r = _resolver([c], rows)
    assert r.has_pattern(c.id) is True
    assert r.works_on(c.id, MON, "AM") is False


@pytest.mark.django_db
def test_a_one_shot_iterable_of_pattern_rows_still_populates_has_pattern():
    """__init__ walks pattern_rows twice (once inside PatternResolver, once
    for _with_pattern). A generator would silently leave _with_pattern empty
    if the rows were not coerced to a list first."""
    c = make_clinician("Genwise", initials="GW")
    row = _pattern(c, 0, "AM")
    r = AvailabilityResolver((row for row in [row]), [c], [], {})
    assert r.has_pattern(c.id) is True
    assert r.works_on(c.id, MON, "AM") is True


# --------------------------------------------------------- Breathe overlay ---

def _mapping():
    return BreatheLeaveMapping.as_dict()


@pytest.mark.django_db
def test_a_full_day_absence_covers_both_parts():
    c = make_clinician(); rows = make_pattern(c)
    make_absence(c, MON)
    r = availability.AvailabilityResolver(rows, [c], [BreatheAbsence.objects.get()], _mapping())
    assert r.on_leave(c.id, MON, "AM") and r.on_leave(c.id, MON, "PM")
    assert r.available(c.id, MON, "AM") is False


@pytest.mark.django_db
def test_a_half_start_afternoon_leaves_the_morning_available():
    c = make_clinician(); rows = make_pattern(c)
    make_absence(c, MON, MON + timedelta(days=2), half_start=True, half_start_am_pm="PM")
    r = availability.AvailabilityResolver(rows, [c], list(BreatheAbsence.objects.all()), _mapping())
    assert r.on_leave(c.id, MON, "AM") is False
    assert r.on_leave(c.id, MON, "PM") is True
    assert r.on_leave(c.id, MON + timedelta(days=1), "AM") is True


@pytest.mark.django_db
def test_leave_type_resolves_through_the_mapping():
    c = make_clinician(); rows = make_pattern(c)
    make_absence(c, MON, kind="sickness")
    r = availability.AvailabilityResolver(rows, [c], list(BreatheAbsence.objects.all()), _mapping())
    assert r.leave_type(c.id, MON, "AM").code == "SICK"


@pytest.mark.django_db
def test_an_unmapped_reason_falls_back_to_the_kind_default():
    c = make_clinician(); rows = make_pattern(c)
    make_absence(c, MON, kind="other", reason="Jury service")
    r = availability.AvailabilityResolver(rows, [c], list(BreatheAbsence.objects.all()), _mapping())
    assert r.leave_type(c.id, MON, "AM").code == "OTH"


@pytest.mark.django_db
def test_leave_does_not_change_works_on():
    c = make_clinician(); rows = make_pattern(c)
    make_absence(c, MON)
    r = availability.AvailabilityResolver(rows, [c], list(BreatheAbsence.objects.all()), _mapping())
    assert r.works_on(c.id, MON, "AM") is True


@pytest.mark.django_db
def test_an_unmapped_kind_still_blocks_scheduling():
    """Availability must never fail open. A sickness absence whose mapping
    row has been deleted (an admin misconfiguration, or a kind added to
    Breathe with nothing set up for it yet) must still take the clinician
    off the rota — a chip having nothing to render is a separate question
    from whether the fill engine may schedule over it."""
    from rota.models import BreatheLeaveMapping as Mapping

    c = make_clinician(); rows = make_pattern(c)
    make_absence(c, MON, kind="sickness")
    Mapping.objects.filter(kind="sickness", reason="").delete()
    r = availability.AvailabilityResolver(rows, [c], list(BreatheAbsence.objects.all()), _mapping())
    assert r.available(c.id, MON, "AM") is False
    assert r.leave_type(c.id, MON, "AM") is None
