"""Linking a clinician to a Breathe employee, in the admin."""

import json
from pathlib import Path
from unittest import mock

import pytest
from django.core.cache import cache

from rota.models import Clinician
from tests.factories import make_clinician

pytestmark = pytest.mark.django_db

FIX = Path(__file__).resolve().parent / "fixtures" / "breathe"
EMPLOYEES = [{k: e.get(k) for k in ("id", "first_name", "last_name", "email",
                                     "employee_ref", "status", "leaving_date")}
             for e in json.loads((FIX / "employees.json").read_text())["employees"]]


class FakeClient:
    def __init__(self, fail=False): self.fail = fail; self.calls = 0
    def employees(self):
        self.calls += 1
        if self.fail:
            from rota.services.breathe.client import BreatheError
            raise BreatheError("down", path="/employees")
        return EMPLOYEES


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear(); yield; cache.clear()


def _with(client):
    return mock.patch("rota.admin_widgets.from_settings", return_value=client)


def test_the_field_is_a_dropdown_of_employees(staff_client):
    with _with(FakeClient()):
        html = staff_client.get("/admin/rota/clinician/add/").content.decode()
    assert '<select name="breathe_employee_id"' in html
    assert "Anya Sharma" in html and "EMP001" in html
    assert "anya.sharma@" in html


def test_ex_employees_are_listed_and_marked(staff_client):
    with _with(FakeClient()):
        html = staff_client.get("/admin/rota/clinician/add/").content.decode()
    assert "James Jefferies" in html
    assert "ex-employee" in html.lower()


def test_the_employee_list_is_cached(staff_client):
    client = FakeClient()
    with _with(client):
        staff_client.get("/admin/rota/clinician/add/")
        staff_client.get("/admin/rota/clinician/add/")
    assert client.calls == 1


def test_unreachable_breathe_degrades_to_a_number_input(staff_client):
    with _with(FakeClient(fail=True)):
        html = staff_client.get("/admin/rota/clinician/add/").content.decode()
    assert '<input type="number" name="breathe_employee_id"' in html
    assert "could not reach breathe" in html.lower()


def test_unconfigured_breathe_degrades_the_same_way(staff_client):
    with mock.patch("rota.admin_widgets.from_settings", return_value=None):
        html = staff_client.get("/admin/rota/clinician/add/").content.decode()
    assert '<input type="number" name="breathe_employee_id"' in html


def test_an_email_match_is_preselected_on_an_unlinked_clinician(staff_client, gp_user):
    gp_user.email = "anya.sharma@breathehrdevachnidltd.com"; gp_user.save()
    c = make_clinician("Anya", user=gp_user)
    with _with(FakeClient()):
        html = staff_client.get(f"/admin/rota/clinician/{c.pk}/change/").content.decode()
    assert 'value="2340355" selected' in html


def test_a_suggestion_never_overrides_an_existing_link(staff_client, gp_user):
    gp_user.email = "anya.sharma@breathehrdevachnidltd.com"; gp_user.save()
    c = make_clinician("Anya", user=gp_user, breathe_employee_id=2340353)  # Omar, deliberately
    with _with(FakeClient()):
        html = staff_client.get(f"/admin/rota/clinician/{c.pk}/change/").content.decode()
    assert 'value="2340353" selected' in html
    assert 'value="2340355" selected' not in html


def test_saving_the_form_stores_the_link(staff_client):
    c = make_clinician("Link Me")
    with _with(FakeClient()):
        resp = staff_client.post(f"/admin/rota/clinician/{c.pk}/change/", {
            "name": "Link Me", "initials": "LM", "group": c.group_id, "active": "on",
            "breathe_employee_id": "2340357",
            "trainee_profile-TOTAL_FORMS": "0", "trainee_profile-INITIAL_FORMS": "0",
            "commitments-TOTAL_FORMS": "0", "commitments-INITIAL_FORMS": "0",
        })
    assert resp.status_code == 302, resp.content.decode()[:500]
    assert Clinician.objects.get(pk=c.pk).breathe_employee_id == 2340357


def test_the_list_shows_linked_name_and_filters(staff_client):
    make_clinician("Linked", breathe_employee_id=2340355)
    make_clinician("Loose")
    with _with(FakeClient()):
        html = staff_client.get("/admin/rota/clinician/").content.decode()
        linked = staff_client.get("/admin/rota/clinician/?breathe=linked").content.decode()
        loose = staff_client.get("/admin/rota/clinician/?breathe=unlinked").content.decode()
    assert "Anya Sharma" in html and "not linked" in html.lower()
    assert "Linked" in linked and "Loose" not in linked
    assert "Loose" in loose and "Linked" not in loose
