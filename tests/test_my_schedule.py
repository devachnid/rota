from datetime import timedelta

import pytest

from rota.models import PracticeSettings, SwapRequest
from tests.factories import MON, make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db


def test_shows_upcoming_sessions(gp_client, gp_user):
    PracticeSettings.load()
    c = make_clinician(user=gp_user)
    from datetime import date
    today = date.today()
    make_entry(c, day=today + timedelta(days=1), part="AM",
               session_type=make_session_type("Routine", code="ROUT"))
    html = gp_client.get("/me/").content.decode()
    assert "ROUT" in html


def test_swap_awaiting_my_acceptance_listed(gp_client, gp_user):
    PracticeSettings.load()
    me = make_clinician("Me Person", user=gp_user)
    other = make_clinician("Other Person")
    SwapRequest.objects.create(
        proposer=other, proposer_day=MON, proposer_part="AM",
        colleague=me, colleague_day=MON, colleague_part="PM")
    html = gp_client.get("/me/").content.decode()
    assert "Other Person" in html and "Accept" in html


def test_no_clinician_profile_is_friendly(admin_client):
    PracticeSettings.load()
    resp = admin_client.get("/me/")
    assert resp.status_code == 200
    assert b"No clinician profile" in resp.content
