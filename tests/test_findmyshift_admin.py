"""Linking a clinician to a FindMyShift staff member, in the admin."""

import json
from pathlib import Path
from unittest import mock

import pytest
from django.core.cache import cache

from rota.models import Clinician
from rota.services.findmyshift.client import STAFF_FIELDS
from tests.factories import make_clinician, make_group

pytestmark = pytest.mark.django_db

FIX = Path(__file__).resolve().parent / "fixtures" / "findmyshift"
STAFF = [{k: s.get(k) for k in STAFF_FIELDS}
         for s in json.loads((FIX / "staff.json").read_text())]


class FakeClient:
    def __init__(self, fail=False): self.fail = fail; self.calls = 0
    def staff(self, team_id=None):
        self.calls += 1
        if self.fail:
            from rota.services.findmyshift.client import FindMyShiftError
            raise FindMyShiftError("down", method="staff/list")
        return STAFF


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear(); yield; cache.clear()


def _with(client):
    return mock.patch("rota.admin_widgets.from_settings", return_value=client)


def test_the_field_is_a_dropdown_of_staff(staff_client):
    with _with(FakeClient()):
        html = staff_client.get("/admin/rota/clinician/add/").content.decode()
    assert '<select name="findmyshift_staff_id"' in html
    assert "Anya Sharma" in html and "EMP005" in html
    assert "anya.sharma@" in html


def test_staff_who_have_left_are_listed_and_marked(staff_client):
    with _with(FakeClient()):
        html = staff_client.get("/admin/rota/clinician/add/").content.decode()
    assert "James Jefferies" in html
    assert "(left)" in html


def test_the_staff_list_is_cached(staff_client):
    client = FakeClient()
    with _with(client):
        staff_client.get("/admin/rota/clinician/add/")
        staff_client.get("/admin/rota/clinician/add/")
    assert client.calls == 1


def test_unreachable_findmyshift_degrades_to_a_text_input(staff_client):
    with _with(FakeClient(fail=True)):
        html = staff_client.get("/admin/rota/clinician/add/").content.decode()
    assert '<input type="text" name="findmyshift_staff_id"' in html
    assert "could not reach findmyshift" in html.lower()


def test_unconfigured_findmyshift_degrades_the_same_way(staff_client):
    with mock.patch("rota.admin_widgets.from_settings", return_value=None):
        html = staff_client.get("/admin/rota/clinician/add/").content.decode()
    assert '<input type="text" name="findmyshift_staff_id"' in html


def test_an_email_match_is_preselected_on_an_unlinked_clinician(staff_client, gp_user):
    gp_user.email = "anya.sharma@example.org"; gp_user.save()
    c = make_clinician("Anya", user=gp_user)
    with _with(FakeClient()):
        html = staff_client.get(f"/admin/rota/clinician/{c.pk}/change/").content.decode()
    assert 'value="S5" selected' in html


def test_a_suggestion_never_overrides_an_existing_link(staff_client, gp_user):
    gp_user.email = "anya.sharma@example.org"; gp_user.save()
    c = make_clinician("Anya", user=gp_user, findmyshift_staff_id="S3")  # Omar, deliberately
    with _with(FakeClient()):
        html = staff_client.get(f"/admin/rota/clinician/{c.pk}/change/").content.decode()
    assert 'value="S3" selected' in html
    assert 'value="S5" selected' not in html


def test_saving_the_form_stores_the_link(staff_client):
    c = make_clinician("Link Me")
    with _with(FakeClient()):
        resp = staff_client.post(f"/admin/rota/clinician/{c.pk}/change/", {
            "name": "Link Me", "initials": "LM", "group": c.group_id, "display_order": "100", "active": "on",
            "findmyshift_staff_id": "S4",
            "trainee_profile-TOTAL_FORMS": "0", "trainee_profile-INITIAL_FORMS": "0",
            "commitments-TOTAL_FORMS": "0", "commitments-INITIAL_FORMS": "0",
        })
    assert resp.status_code == 302, resp.content.decode()[:500]
    assert Clinician.objects.get(pk=c.pk).findmyshift_staff_id == "S4"


def test_the_list_shows_linked_name_and_filters(staff_client):
    make_clinician("Linked", findmyshift_staff_id="S5")
    make_clinician("Loose")
    with _with(FakeClient()):
        html = staff_client.get("/admin/rota/clinician/").content.decode()
        linked = staff_client.get("/admin/rota/clinician/?findmyshift=linked").content.decode()
        loose = staff_client.get("/admin/rota/clinician/?findmyshift=unlinked").content.decode()
    assert "Anya Sharma" in html and "not linked" in html.lower()
    assert "Linked" in linked and "Loose" not in linked
    assert "Loose" in loose and "Linked" not in loose


def test_the_list_does_not_call_a_locum_unlinked(staff_client):
    """A locum books their own sessions and has no time off to read, so the
    column says so instead of flagging something to fix."""
    locums = make_group("Locum GPs", is_locum_group=True, display_order=99)
    make_clinician("Laura Locum", group=locums)
    with _with(FakeClient()):
        html = staff_client.get("/admin/rota/clinician/").content.decode()
    assert "locum — not on FindMyShift" in html
    assert "not linked" not in html.lower()
