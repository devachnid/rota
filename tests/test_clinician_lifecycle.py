"""Clinician start and end dates.

They sit alongside `active` rather than replacing it: `active` is the manual
"not schedulable right now" switch, the dates are the contractual window.
Both feed one composition in AvailabilityResolver so they cannot disagree.
"""

from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError

from tests.factories import make_clinician

TODAY = date(2026, 9, 15)
BEFORE = date(2026, 9, 1)
AFTER = date(2026, 9, 30)


@pytest.mark.django_db
def test_no_dates_means_always_in_window():
    c = make_clinician("Open Ended", initials="OE")
    assert c.start_date is None and c.end_date is None
    assert c.in_window(date(1999, 1, 1)) is True
    assert c.in_window(date(2099, 1, 1)) is True


@pytest.mark.django_db
def test_the_window_is_inclusive_at_both_ends():
    c = make_clinician("Bounded", initials="BD")
    c.start_date, c.end_date = BEFORE, AFTER
    assert c.in_window(BEFORE) is True
    assert c.in_window(AFTER) is True
    assert c.in_window(BEFORE - timedelta(days=1)) is False
    assert c.in_window(AFTER + timedelta(days=1)) is False


@pytest.mark.django_db
def test_a_start_date_alone_bounds_only_the_past():
    c = make_clinician("Starter", initials="ST")
    c.start_date = TODAY
    assert c.in_window(TODAY - timedelta(days=1)) is False
    assert c.in_window(date(2099, 1, 1)) is True


@pytest.mark.django_db
def test_an_end_date_alone_bounds_only_the_future():
    c = make_clinician("Leaver", initials="LR")
    c.end_date = TODAY
    assert c.in_window(date(1999, 1, 1)) is True
    assert c.in_window(TODAY + timedelta(days=1)) is False


@pytest.mark.django_db
def test_an_end_date_before_the_start_date_is_refused():
    c = make_clinician("Backwards", initials="BW")
    c.start_date, c.end_date = AFTER, BEFORE
    with pytest.raises(ValidationError):
        c.full_clean()


@pytest.mark.django_db
def test_saving_a_window_warns_about_entries_outside_it_but_deletes_nothing(
    staff_client
):
    """Silently destroying published rota because someone typed a date would
    be the wrong trade."""
    from rota.models import RotaEntry
    from tests.factories import make_entry, make_session_type, MON

    c = make_clinician("Windowed", initials="WD")
    make_entry(c, part="AM", session_type=make_session_type("Routine", code="RT"))
    before = RotaEntry.objects.filter(clinician=c).count()
    assert before == 1

    r = staff_client.post(
        f"/admin/rota/clinician/{c.pk}/change/",
        {"name": c.name, "initials": c.initials, "group": c.group_id,
         "active": "on", "leave_entitlement_sessions": "0",
         "start_date": (MON + timedelta(days=365)).isoformat(),
         "end_date": "",
         "trainee_profile-TOTAL_FORMS": "0", "trainee_profile-INITIAL_FORMS": "0"},
        follow=True,
    )
    assert RotaEntry.objects.filter(clinician=c).count() == before, (
        "saving a date window deleted rota entries"
    )
    assert any("outside" in str(m) for m in r.context["messages"]), (
        "no warning was shown about the entries outside the new window"
    )
