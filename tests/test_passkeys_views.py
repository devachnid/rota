"""The passkey endpoints and pages, driven end to end through the test
client with a software authenticator."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_login_failed
from django.test import Client

from accounts.models import Passkey
from tests.soft_authenticator import SoftAuthenticator

pytestmark = pytest.mark.django_db
User = get_user_model()
REG_OPTIONS = "/accounts/passkeys/register/options/"
REGISTER = "/accounts/passkeys/register/"
LOGIN_OPTIONS = "/accounts/passkeys/login/options/"
LOGIN = "/accounts/passkeys/login/"


def _post_json(client, url, payload=None):
    return client.post(url, data=json.dumps(payload or {}), content_type="application/json")


def _enrol(client, auth, name="my phone"):
    options = _post_json(client, REG_OPTIONS).json()
    return _post_json(client, REGISTER, {"credential": auth.create(options), "name": name})


# --- enrolling ---------------------------------------------------------------

def test_registration_endpoints_need_a_login_and_a_post(client, gp_client):
    assert client.post(REG_OPTIONS).status_code == 302
    assert client.post(REGISTER).status_code == 302
    assert gp_client.get(REG_OPTIONS).status_code == 405


def test_enrolling_a_passkey_from_the_account_page(gp_client, gp_user):
    auth = SoftAuthenticator()
    resp = _enrol(gp_client, auth)
    assert resp.status_code == 200 and resp.json()["name"] == "my phone"
    passkey = Passkey.objects.get(user=gp_user)
    assert passkey.credential_id == auth.id and resp.json()["id"] == passkey.pk
    html = gp_client.get("/accounts/account/").content.decode()
    assert "Passkeys" in html and "my phone" in html and "Never" in html
    assert 'id="passkey-add"' in html and "js/passkeys.js" in html
    assert f'action="/accounts/passkeys/{passkey.pk}/remove/"' in html


def test_the_empty_state_and_the_add_button_are_there_before_any_passkey(gp_client):
    html = gp_client.get("/accounts/account/").content.decode()
    assert "No passkeys yet." in html and "Add a passkey" in html
    assert 'name="name"' in html and 'maxlength="60"' in html


def test_a_malformed_or_rejected_registration_is_a_400_with_a_reason(gp_client):
    assert _post_json(gp_client, REGISTER, {"credential": "nope"}).json() == {"error": "Malformed request."}
    assert gp_client.post(REGISTER, data="not json", content_type="application/json").status_code == 400
    options = _post_json(gp_client, REG_OPTIONS).json()
    evil = SoftAuthenticator(origin="https://evil.example").create(options)
    resp = _post_json(gp_client, REGISTER, {"credential": evil})
    assert resp.status_code == 400 and "could not be verified" in resp.json()["error"]
    assert Passkey.objects.count() == 0


def test_the_json_endpoints_are_csrf_protected(gp_user):
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(gp_user)
    assert _post_json(strict, REG_OPTIONS).status_code == 403
    assert _post_json(Client(enforce_csrf_checks=True), LOGIN_OPTIONS).status_code == 403


# --- removing ----------------------------------------------------------------

def test_a_person_removes_their_own_passkey_and_nobody_elses(gp_client, gp_user, admin_client):
    _enrol(gp_client, SoftAuthenticator(), name="old phone")
    passkey = Passkey.objects.get()
    assert admin_client.post(f"/accounts/passkeys/{passkey.pk}/remove/").status_code == 404
    assert gp_client.get(f"/accounts/passkeys/{passkey.pk}/remove/").status_code == 405
    resp = gp_client.post(f"/accounts/passkeys/{passkey.pk}/remove/", follow=True)
    assert resp.redirect_chain[-1][0] == "/accounts/account/"
    assert "Passkey “old phone” removed." in resp.content.decode()
    assert not Passkey.objects.exists()
