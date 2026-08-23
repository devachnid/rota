from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model

from rota.models import ClosedDay, LeaveRequest, PracticeSettings, RotaEntry
from rota.services import leave as leave_svc
from tests.factories import (MON, make_clinician, make_entry, make_pattern,
                             make_session_type)

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def annual_leave(db):
    return make_session_type("Annual leave", category="ABSENCE",
                             counts_toward_entitlement=True)


def _request(clinician, st, start=MON, end=None):
    return LeaveRequest.objects.create(
        clinician=clinician, session_type=st,
        start_date=start, end_date=end or start + timedelta(days=4))


def test_sessions_affected_respects_pattern_and_closures(annual_leave):
    PracticeSettings.load()
    c = make_clinician()
    make_pattern(c, weekdays=(0, 1), parts=("AM",))
    ClosedDay.objects.create(day=MON, reason="BH")
    req = _request(c, annual_leave)
    assert leave_svc.sessions_affected(req) == [(MON + timedelta(days=1), "AM")]


def test_approve_overwrites_and_publishes(annual_leave, admin_user):
    PracticeSettings.load()
    c = make_clinician()
    make_pattern(c, weekdays=(0,), parts=("AM", "PM"))
    duty = make_session_type("Duty", fairness_tracked=True)
    make_entry(c, part="AM", session_type=duty)
    req = _request(c, annual_leave, start=MON, end=MON)
    overwritten = leave_svc.entries_overwritten(req)
    assert [e.session_type.code for e in overwritten] == ["DUTY"]
    leave_svc.approve(admin_user, req)
    req.refresh_from_db()
    assert req.status == LeaveRequest.Status.APPROVED
    types = set(RotaEntry.objects.filter(clinician=c, day=MON)
                .values_list("session_type__name", flat=True))
    assert types == {"Annual leave"}
    assert all(e.is_published for e in RotaEntry.objects.all())


def test_leave_summary(annual_leave):
    PracticeSettings.load()
    c = make_clinician(leave_entitlement_sessions=60)
    past, future = MON - timedelta(days=30), MON + timedelta(days=30)
    make_entry(c, day=past, part="AM", session_type=annual_leave)
    make_entry(c, day=future, part="AM", session_type=annual_leave)
    s = leave_svc.leave_summary(c, MON)
    assert s == {"entitlement": 60, "taken": 1, "booked": 1, "remaining": 58}


def test_gp_can_submit_and_admin_approves_via_views(annual_leave, gp_client,
                                                    admin_client, gp_user):
    PracticeSettings.load()
    c = make_clinician(user=gp_user)
    make_pattern(c, weekdays=(0,), parts=("AM",))
    resp = gp_client.post("/me/leave/new/", {
        "session_type_id": annual_leave.id, "start_date": MON.isoformat(),
        "end_date": MON.isoformat(), "message": "wedding"})
    assert resp.status_code == 302
    req = LeaveRequest.objects.get()
    html = admin_client.get("/requests/").content.decode()
    assert "wedding" in html
    admin_client.post(f"/requests/leave/{req.pk}/approve/")
    req.refresh_from_db()
    assert req.status == LeaveRequest.Status.APPROVED


def test_leave_year_bounds_handles_feb_29_configured_start():
    # A leave year configured to start 29 Feb ("end of February") must not
    # 500 in a non-leap year, where date(year, 2, 29) doesn't exist. Both
    # a non-leap-year `today` and a leap-year `today` must clamp cleanly.
    s = PracticeSettings.load()
    s.leave_year_start_month = 2
    s.leave_year_start_day = 29
    s.save()

    non_leap_today = date(2025, 6, 15)  # 2025: Feb has 28 days
    start, end = leave_svc.leave_year_bounds(non_leap_today)
    assert start == date(2025, 2, 28)
    assert end == date(2026, 2, 27)
    assert start <= non_leap_today <= end

    leap_today = date(2024, 6, 15)  # 2024: Feb has 29 days
    start, end = leave_svc.leave_year_bounds(leap_today)
    assert start == date(2024, 2, 29)
    assert end == date(2025, 2, 27)
    assert start <= leap_today <= end


def test_inbox_admin_only(gp_client):
    assert gp_client.get("/requests/").status_code == 403


def test_leave_new_rejects_backwards_range(annual_leave, gp_client, gp_user):
    make_clinician(user=gp_user)
    resp = gp_client.post("/me/leave/new/", {
        "session_type_id": annual_leave.id,
        "start_date": (MON + timedelta(days=4)).isoformat(),
        "end_date": MON.isoformat(),
        "message": "oops"})
    assert resp.status_code == 200
    assert b"must not be before" in resp.content
    assert not LeaveRequest.objects.exists()
