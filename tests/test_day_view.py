"""The day view: who is on, and nothing about whether that is enough.

The screen deliberately carries no coverage, staffing or group warnings for
either role. A GP reading a roster can judge cover themselves, and an app
that says "covered" when it is not is worse than one that says nothing.
"""

from datetime import date

import pytest

from rota.models import LeaveRequest, PatternSlot, PracticeSettings
from tests.factories import (make_clinician, make_entry, make_pattern,
                             make_session_type)

pytestmark = pytest.mark.django_db

TUE = date(2026, 9, 8)


def _html(client, day=TUE):
    PracticeSettings.load()
    return client.get(f"/rota/day/{day.isoformat()}/").content.decode()


def test_a_clinician_working_the_day_appears_with_both_parts(gp_client, gp_user):
    c = make_clinician("Emma Hall", user=gp_user)
    make_pattern(c)
    rout = make_session_type("Routine", code="ROUT")
    make_entry(c, day=TUE, part="AM", session_type=rout)
    make_entry(c, day=TUE, part="PM", session_type=rout)
    html = _html(gp_client)
    assert "Emma Hall" in html
    assert html.count("ROUT") >= 2


def test_a_clinician_on_leave_all_day_is_in_the_leave_group_not_the_roster(
        gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Anwer Al-Hasani")
    make_pattern(c)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    make_entry(c, day=TUE, part="AM", session_type=al)
    make_entry(c, day=TUE, part="PM", session_type=al)
    resp = _html(gp_client)
    assert "Anwer Al-Hasani" in resp
    assert "On leave" in resp


def test_half_a_day_of_leave_keeps_the_clinician_in_the_roster(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Esther Lomas")
    make_pattern(c)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    rout = make_session_type("Routine", code="ROUT")
    make_entry(c, day=TUE, part="AM", session_type=al)
    make_entry(c, day=TUE, part="PM", session_type=rout)
    html = _html(gp_client)
    assert "Esther Lomas" in html and "ROUT" in html


def test_someone_who_does_not_work_that_day_is_on_the_not_in_line(
        gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Nesreen Mayoub")
    make_pattern(c, weekdays=(0,))  # Mondays only; TUE is a Tuesday
    html = _html(gp_client)
    assert "Not in" in html and "Nesreen Mayoub" in html


def test_a_gp_sees_no_staffing_warnings(gp_client, gp_user):
    """The week grid warns. This screen never does, for either role."""
    make_clinician("Viewer", user=gp_user)
    html = _html(gp_client)
    for phrase in ("clinical GP", "No Duty cover", "in (AM)"):
        assert phrase not in html


def test_an_admin_sees_no_staffing_warnings_either(admin_client):
    html = _html(admin_client)
    for phrase in ("clinical GP", "No Duty cover", "in (AM)"):
        assert phrase not in html


def test_a_gp_does_not_see_unpublished_entries(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Harri Davies")
    make_pattern(c)
    draft = make_session_type("Vasectomy", code="VAS")
    make_entry(c, day=TUE, part="AM", session_type=draft, is_published=False)
    assert "VAS" not in _html(gp_client)


def test_an_admin_does_see_unpublished_entries(admin_client):
    c = make_clinician("Harri Davies")
    make_pattern(c)
    draft = make_session_type("Vasectomy", code="VAS")
    make_entry(c, day=TUE, part="AM", session_type=draft, is_published=False)
    assert "VAS" in _html(admin_client)


def test_a_bare_day_url_renders_today(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    PracticeSettings.load()
    resp = gp_client.get("/rota/day/")
    assert resp.status_code == 200
    # A bare day-of-month number ("8") appears in plenty of markup that has
    # nothing to do with today's date. The header's full formatted date is
    # what the page actually promises to show, so assert that instead — a
    # test that would pass against a blank page is not a test.
    assert date.today().strftime("%-d %b") in resp.content.decode()


def test_a_malformed_date_falls_back_to_today_like_the_grid_does(
        gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    PracticeSettings.load()
    resp = gp_client.get("/rota/day/not-a-date/")
    assert resp.status_code == 200


def test_the_day_note_is_shown_to_everyone(gp_client, gp_user):
    from rota.models import DayNote
    make_clinician("Viewer", user=gp_user)
    DayNote.objects.create(day=TUE, text="Flu clinic in the back room")
    assert "Flu clinic in the back room" in _html(gp_client)
