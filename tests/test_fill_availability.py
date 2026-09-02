"""The fill engine must not schedule someone who is unavailable.

Two new reasons to be unavailable: outside the contractual date window, and
on a Breathe absence. The absence check is deliberately independent of rota
entries — entries only exist where the pattern said the clinician works, so a
pattern widened after the absence was written would otherwise expose it to
a re-run.
"""

from datetime import date, timedelta

import pytest

from rota.models import CoverageRule, PatternSlot, PracticeSettings, RotaEntry
from rota.services.fill import run_fill
from tests.factories import make_absence, make_clinician, make_session_type

MON = date(2026, 9, 7)
FRI = MON + timedelta(days=4)


def _full_pattern(clinician):
    for weekday in range(5):
        for part in ("AM", "PM"):
            PatternSlot.objects.create(
                clinician=clinician, weekday=weekday, part=part,
                works=True, effective_from=date(2025, 1, 1))


@pytest.fixture
def duty(db):
    PracticeSettings.load()
    st = make_session_type("Duty", code="DUTY")
    CoverageRule.objects.create(session_type=st, unit="SESSION",
                                parts="BOTH", weekdays="0-4", count=1)
    return st


@pytest.mark.django_db
def test_a_clinician_outside_their_window_is_not_scheduled(duty, admin_user):
    c = make_clinician("Leaver", initials="LV")
    _full_pattern(c)
    c.end_date = MON - timedelta(days=1)
    c.save()
    run_fill(admin_user, MON, FRI)
    assert RotaEntry.objects.filter(clinician=c).count() == 0


@pytest.mark.django_db
def test_a_clinician_on_approved_leave_is_not_scheduled(duty, admin_user):
    c = make_clinician("Away", initials="AW")
    _full_pattern(c)
    make_absence(c, MON, FRI)
    run_fill(admin_user, MON, FRI)
    assert RotaEntry.objects.filter(clinician=c, session_type=duty).count() == 0


@pytest.mark.django_db
def test_leave_is_respected_even_when_approval_wrote_no_entries(duty, admin_user):
    """The case that made this necessary: leave written while the clinician
    had no pattern, the pattern entered afterwards. No entries exist, so
    `is_free` sees nothing — only reading the absence catches it."""
    c = make_clinician("Late Pattern", initials="LP")
    make_absence(c, MON, FRI)
    assert RotaEntry.objects.filter(clinician=c).count() == 0
    _full_pattern(c)   # pattern arrives after the absence was written

    run_fill(admin_user, MON, FRI)
    assert RotaEntry.objects.filter(clinician=c).count() == 0, (
        "the fill scheduled over an absence that had no entries"
    )


@pytest.mark.django_db
def test_an_available_clinician_is_still_scheduled(duty, admin_user):
    """The control: none of the above should stop ordinary scheduling."""
    c = make_clinician("Normal", initials="NM")
    _full_pattern(c)
    run_fill(admin_user, MON, FRI)
    assert RotaEntry.objects.filter(clinician=c, session_type=duty).count() > 0


def test_no_scheduling_call_site_still_uses_the_old_name():
    """`ctx.works_on` no longer exists. If a call site is reintroduced meaning
    "pattern only", it silently ignores the date window and leave."""
    from pathlib import Path
    import rota.services.fill as fill_pkg

    offenders = []
    for path in Path(fill_pkg.__file__).parent.glob("*.py"):
        for lineno, line in enumerate(path.read_text().split("\n"), 1):
            if "ctx.works_on" in line:
                offenders.append(f"{path.name}:{lineno}")
    assert not offenders, (
        "these call sites use ctx.works_on, which no longer accounts for the "
        f"date window or leave: {', '.join(offenders)}"
    )
