"""A published entry standing on Breathe leave.

Leave used to be approved in the rota, and approving it overwrote the
entries. Breathe owns leave now, and the ordinary sequence — publish the
week, then leave is approved in Breathe — leaves a session against someone
who is not coming in. The cell still shows the session (an entry beats leave
in cell_state, by design) and fill will not clear it, so an admin warning is
the signal. Non-admins see nothing: judgement signals are the admin's.
"""

from datetime import date, timedelta

import pytest

from rota.models import BreatheLeaveMapping, PracticeSettings
from rota.services.warnings import day_warnings
from tests.factories import (MON, make_absence, make_clinician, make_entry,
                             make_pattern, make_session_type)

pytestmark = pytest.mark.django_db

TEXT = "rostered on Breathe leave"


@pytest.fixture(autouse=True)
def _quiet_other_warnings(db):
    """Only the Breathe rule is under test here."""
    PracticeSettings.objects.update_or_create(
        pk=1, defaults={"min_clinical_per_session": 0})


def _rostered_on_leave(**absence_kw):
    c = make_clinician("Ann Able")
    make_pattern(c)
    rout = make_session_type("Routine", code="ROUT")
    make_entry(c, day=MON, part="AM", session_type=rout)
    make_entry(c, day=MON, part="PM", session_type=rout)
    make_absence(c, MON, **absence_kw)
    return c


def _breathe(day=MON, **kw):
    return [w for w in day_warnings(day, **kw) if w.code == "breathe"]


def test_a_published_entry_over_a_full_day_absence_warns_for_both_parts():
    _rostered_on_leave()
    warnings = _breathe()
    assert [w.part for w in warnings] == ["AM", "PM"]
    assert warnings[0].message == "1 rostered on Breathe leave (AM)"
    assert warnings[1].message == "1 rostered on Breathe leave (PM)"


def test_a_pm_only_absence_warns_for_pm_only():
    _rostered_on_leave(half_start=True, half_start_am_pm="PM",
                       half_end=True, half_end_am_pm="PM")
    assert [w.part for w in _breathe()] == ["PM"]


def test_a_draft_entry_counts_too():
    """A week is drafted, then leave is approved: the admin grid shows drafts,
    and the conflict is there to fix before publishing."""
    c = make_clinician("Ann Able")
    make_pattern(c)
    make_entry(c, day=MON, part="AM", is_published=False,
               session_type=make_session_type("Routine", code="ROUT"))
    make_absence(c, MON)
    assert [w.part for w in _breathe()] == ["AM"]
    assert _breathe(include_drafts=False) == [], "a GP's view has no draft to conflict with"


def test_no_entry_no_warning():
    c = make_clinician("Ann Able")
    make_pattern(c)
    make_absence(c, MON)
    assert _breathe() == []


def test_an_unmapped_absence_still_warns():
    """The rule asks the resolver, not the mapping: an absence that renders no
    chip is still someone who is not coming in."""
    BreatheLeaveMapping.objects.filter(kind="holiday").delete()
    _rostered_on_leave()
    assert [w.part for w in _breathe()] == ["AM", "PM"]


def test_the_warning_appears_in_the_admin_grids_day_header(admin_client):
    _rostered_on_leave()
    html = admin_client.get(f"/rota/?week={MON.isoformat()}").content.decode()
    assert "1 rostered on Breathe leave (AM)" in html


def test_a_non_admin_grid_carries_no_such_text(gp_client, gp_user):
    c = _rostered_on_leave()
    c.user = gp_user
    c.save()
    html = gp_client.get(f"/rota/?week={MON.isoformat()}").content.decode()
    assert TEXT not in html


# --------- the mapping decides chips, never who is counted as off ---------
#
# leave_type() goes through BreatheLeaveMapping; on_leave() does not. Two
# consumers still asked the first — the day view's partition and My
# Schedule's week label — so with a kind's default mapping row missing, the
# screens said "in" about someone the scheduler already refused to give
# sessions to. Defaults are seeded and undeletable in the admin, so these
# delete the row directly: the point is that the answer no longer depends on
# it at all.


def _sick_with_no_mapping(name="Sam Sick", **kw):
    BreatheLeaveMapping.objects.filter(kind="sickness").delete()
    c = make_clinician(name, **kw)
    make_pattern(c)
    return c


def test_the_day_view_counts_an_unmapped_absence_as_on_leave(admin_client):
    c = _sick_with_no_mapping()
    make_absence(c, MON, kind="sickness")
    html = admin_client.get(f"/rota/day/{MON.isoformat()}/").content.decode()
    assert "0 in &middot; 1 on leave" in html
    assert c.name in html


def test_my_schedule_says_on_leave_all_week_without_a_mapping(gp_client, gp_user):
    c = _sick_with_no_mapping(user=gp_user)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    make_absence(c, monday, monday + timedelta(days=4), kind="sickness")
    assert gp_client.get("/me/").context["weeks"][0]["count_label"] == "On leave all week"
