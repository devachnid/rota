"""What a grid cell shows, and why.

Cell precedence:
    entry exists                -> the entry
    on_leave and ghostable      -> a ghosted leave chip
    works_on                    -> grey: working, nothing allocated
    otherwise                   -> blank: not working

The colours are the reverse of what shipped: blank now means "not here", grey
means "here and unallocated" — the state that needs attention.
"""

from datetime import date, timedelta

import pytest

from rota.models import LeaveRequest, PatternSlot, PracticeSettings
from tests.factories import make_clinician, make_entry, make_session_type

MON = date(2026, 9, 7)


def _pattern(c, weekday, part, works=True):
    PatternSlot.objects.create(clinician=c, weekday=weekday, part=part,
                               works=works, effective_from=date(2025, 1, 1))


def _cells(client, day=MON):
    PracticeSettings.load()
    return client.get(f"/rota/?week={day.isoformat()}").content.decode()


@pytest.mark.django_db
def test_a_worked_but_unallocated_session_is_grey(admin_client):
    c = make_clinician("Grey", initials="GY")
    _pattern(c, 0, "AM")
    html = _cells(admin_client)
    assert "empty-slot" in html, (
        "a worked, unallocated session should carry the grey class"
    )


@pytest.mark.django_db
def test_a_non_working_session_is_blank(admin_client):
    c = make_clinician("Blank", initials="BL")
    _pattern(c, 0, "AM", works=False)
    html = _cells(admin_client)
    assert "unavail" not in html, (
        "the old class is gone; a non-working session is now unstyled"
    )


@pytest.mark.django_db
def test_approved_leave_ghosts_on_a_session_the_clinician_works(admin_client):
    """Approval should have written an entry here and did not — the ghost is
    the signal that something went wrong."""
    c = make_clinician("Ghosted", initials="GH")
    _pattern(c, 0, "AM")
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    LeaveRequest.objects.create(clinician=c, session_type=al,
                                start_date=MON, end_date=MON,
                                status=LeaveRequest.Status.APPROVED)
    html = _cells(admin_client)
    assert "is-ghost" in html
    assert "AL" in html


@pytest.mark.django_db
def test_a_part_timer_gets_no_ghost_on_their_non_working_days(admin_client):
    """The noise case. Ghosting every session a leave request spans would put
    chips on every part-timer's days off, every time they took leave."""
    c = make_clinician("Parttime", initials="PT")
    _pattern(c, 0, "AM")            # works Monday AM only
    _pattern(c, 0, "PM", works=False)
    al = make_session_type("Annual Leave", code="AL2", category="ABSENCE")
    LeaveRequest.objects.create(clinician=c, session_type=al,
                                start_date=MON, end_date=MON + timedelta(days=4),
                                status=LeaveRequest.Status.APPROVED)
    html = _cells(admin_client)
    assert html.count("is-ghost") == 1, (
        f"expected one ghost (Monday AM), got {html.count('is-ghost')}"
    )


@pytest.mark.django_db
def test_a_clinician_with_no_pattern_at_all_gets_ghosts(admin_client):
    """The original complaint: leave approved, nothing anywhere."""
    c = make_clinician("Nopattern", initials="NP")
    al = make_session_type("Annual Leave", code="AL3", category="ABSENCE")
    LeaveRequest.objects.create(clinician=c, session_type=al,
                                start_date=MON, end_date=MON,
                                status=LeaveRequest.Status.APPROVED)
    html = _cells(admin_client)
    assert "is-ghost" in html


@pytest.mark.django_db
def test_a_real_entry_beats_a_ghost(admin_client):
    c = make_clinician("Real", initials="RL")
    _pattern(c, 0, "AM")
    al = make_session_type("Annual Leave", code="AL4", category="ABSENCE")
    make_entry(c, day=MON, part="AM", session_type=al, is_published=True)
    LeaveRequest.objects.create(clinician=c, session_type=al,
                                start_date=MON, end_date=MON,
                                status=LeaveRequest.Status.APPROVED)
    html = _cells(admin_client)
    assert "is-ghost" not in html


@pytest.mark.django_db
def test_warnings_are_admin_only_but_day_notes_are_for_everyone(
    admin_client, gp_client
):
    from rota.models import DayNote
    PracticeSettings.load()
    DayNote.objects.create(day=MON, text="CQC visit")
    make_clinician("Someone", initials="SO")

    admin_html = _cells(admin_client)
    gp_html = _cells(gp_client)

    assert "CQC visit" in admin_html
    assert "CQC visit" in gp_html, "day notes are practice information"
    assert 'class="warn"' in admin_html, "an understaffed day warns an admin"
    assert 'class="warn"' not in gp_html, "warnings are staffing alerts, admin only"
