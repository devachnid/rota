"""Approving leave must not be able to do nothing silently.

`sessions_affected()` intersects the requested range with the clinician's
working pattern. No overlap means zero entries — but the request still flipped
to APPROVED with a success message, so leave "did not work" with no clue why.
"""

from datetime import date, timedelta

import pytest

from rota.models import LeaveRequest, PatternSlot, PracticeSettings, RotaEntry
from tests.factories import make_clinician, make_session_type

MON = date(2026, 9, 7)


def _leave_request(clinician, session_type, days=4):
    return LeaveRequest.objects.create(
        clinician=clinician, session_type=session_type,
        start_date=MON, end_date=MON + timedelta(days=days))


@pytest.fixture
def absence(db):
    PracticeSettings.load()
    return make_session_type("Annual Leave", code="AL", category="ABSENCE")


@pytest.mark.django_db
def test_the_inbox_warns_when_approval_would_write_nothing(admin_client, absence):
    c = make_clinician("Nopattern", initials="NP")
    _leave_request(c, absence)
    html = admin_client.get("/requests/").content.decode()
    assert "no sessions" in html.lower()
    assert "no working pattern" in html.lower(), (
        "the warning must say why, not just that the count is zero"
    )


@pytest.mark.django_db
def test_a_normal_request_shows_a_count_without_alarm(admin_client, absence):
    c = make_clinician("Fulltime", initials="FT")
    for weekday in range(5):
        for part in ("AM", "PM"):
            PatternSlot.objects.create(clinician=c, weekday=weekday, part=part,
                                       works=True, effective_from=date(2025, 1, 1))
    _leave_request(c, absence)
    html = admin_client.get("/requests/").content.decode()
    assert "10 session" in html
    assert "no working pattern" not in html.lower()


@pytest.mark.django_db
def test_approval_still_records_the_decision_when_it_writes_nothing(
    admin_client, absence
):
    """The admin has decided. Blocking them would be wrong; misleading them
    was the bug."""
    c = make_clinician("Nopattern2", initials="N2")
    req = _leave_request(c, absence)
    r = admin_client.post(f"/requests/leave/{req.pk}/approve/", follow=True)
    req.refresh_from_db()
    assert req.status == LeaveRequest.Status.APPROVED
    assert RotaEntry.objects.filter(clinician=c).count() == 0
    assert any("no rota sessions" in str(m).lower() for m in r.context["messages"]), (
        "approving with nothing to write reported plain success"
    )
