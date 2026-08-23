from datetime import date, timedelta

import pytest

from rota.models import ClosedDay, PatternSlot, PracticeSettings
from rota.services import availability, calendar
from tests.factories import MON, make_clinician, make_pattern

pytestmark = pytest.mark.django_db


def test_no_pattern_means_not_working():
    c = make_clinician()
    assert not availability.works_on(c, MON, "AM")


def test_pattern_marks_working_sessions():
    c = make_clinician()
    make_pattern(c, weekdays=(0,), parts=("AM",))
    assert availability.works_on(c, MON, "AM")
    assert not availability.works_on(c, MON, "PM")
    assert not availability.works_on(c, MON + timedelta(days=1), "AM")


def test_latest_effective_row_wins():
    c = make_clinician()
    make_pattern(c, weekdays=(0,), parts=("AM",), effective_from=date(2020, 1, 1))
    make_pattern(c, weekdays=(0,), parts=("AM",), works=False,
                 effective_from=date(2026, 7, 1))
    assert not availability.works_on(c, MON, "AM")
    assert availability.works_on(c, date(2026, 6, 1), "AM")


def test_pattern_resolver_agrees_with_works_on():
    """The batched PatternResolver (used by FillContext and the grid view)
    must agree with the per-call availability.works_on() across the cases
    that exercise the "greatest effective_from on or before the day" rule:
    no rows, a single row, a day falling between two rows, a works=False
    row overriding an earlier works=True row, and a day before any row's
    effective_from.
    """
    # Patterns are keyed by weekday, so every test day below is a Monday
    # (weekday 0), matching weekdays=(0,) on the rows created here.
    no_rows = make_clinician("Nora NoRows")

    single = make_clinician("Sam Single")
    make_pattern(single, weekdays=(0,), parts=("AM",), effective_from=MON)

    multi = make_clinician("Mia Multi")
    make_pattern(multi, weekdays=(0,), parts=("AM",),
                 effective_from=MON - timedelta(weeks=52))
    make_pattern(multi, weekdays=(0,), parts=("AM",), works=False,
                 effective_from=MON)

    clinicians = [no_rows, single, multi]
    resolver = availability.PatternResolver(
        PatternSlot.objects.filter(clinician__in=clinicians)
        .order_by("effective_from")
    )

    cases = [
        (no_rows, MON, False),                            # no rows at all
        (single, MON + timedelta(weeks=4), True),         # single row, day on/after it
        (single, MON - timedelta(weeks=4), False),        # single row, day before its effective_from
        (multi, MON - timedelta(weeks=104), False),       # before any row's effective_from
        (multi, MON - timedelta(weeks=26), True),         # between the two rows: earlier works=True applies
        (multi, MON, False),                              # later works=False row overrides the earlier works=True
    ]
    for clinician, day, expected in cases:
        from_resolver = resolver.works_on(clinician.id, day, "AM")
        from_direct = availability.works_on(clinician, day, "AM")
        assert from_resolver == expected, (clinician.name, day)
        assert from_direct == expected, (clinician.name, day)
        assert from_resolver == from_direct, (clinician.name, day)


def test_weekly_sessions_counts_current_pattern():
    c = make_clinician()
    make_pattern(c, weekdays=(0, 1), parts=("AM", "PM"))
    assert availability.weekly_sessions(c, MON) == 4


def test_is_open_respects_weekends_and_closures():
    PracticeSettings.load()
    assert calendar.is_open(MON)
    assert not calendar.is_open(MON + timedelta(days=5))  # Saturday
    ClosedDay.objects.create(day=MON, reason="Bank holiday")
    assert not calendar.is_open(MON)
