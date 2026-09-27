"""A passkey is a way in that survives a password change, so adding one must
not be open to anyone who finds a signed-in browser (accounts/recent_auth.py).
And the owner hears about each one, and can take them all back with a
password reset."""

import json
import time

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.mail.backends.locmem import EmailBackend as Locmem
from django.test import Client, override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts import recent_auth
from accounts.models import Passkey
from tests.soft_authenticator import SoftAuthenticator

pytestmark = pytest.mark.django_db
User = get_user_model()
REG_OPTIONS = "/accounts/passkeys/register/options/"
REGISTER = "/accounts/passkeys/register/"
LOGIN_OPTIONS = "/accounts/passkeys/login/options/"
LOGIN = "/accounts/passkeys/login/"
NEW_PW = "Brand-new-pass-4471"


def _post_json(client, url, payload=None, **extra):
    return client.post(url, data=json.dumps(payload or {}),
                       content_type="application/json", **extra)


def _stale(client):
    """The session signed in longer ago than the window."""
    session = client.session
    session["rota_auth_at"] = int(time.time()) - recent_auth.WINDOW - 1
    session.save()


def _enrol(client, auth, name="my phone", password=None):
    options = _post_json(client, REG_OPTIONS, {"password": password} if password else None)
    if options.status_code != 200:
        return options
    return _post_json(client, REGISTER, {"credential": auth.create(options.json()), "name": name})


# --- adding one -----------------------------------------------------------------

def test_a_fresh_sign_in_adds_a_passkey_without_the_password(gp_client, gp_user):
    assert _enrol(gp_client, SoftAuthenticator()).status_code == 200
    assert Passkey.objects.filter(user=gp_user).count() == 1


def test_a_borrowed_session_cannot_add_one(gp_client, gp_user):
    """A surgery PC left signed in, found later by someone else."""
    _stale(gp_client)
    resp = _post_json(gp_client, REG_OPTIONS)
    assert resp.status_code == 403 and resp.json()["password"] is True
    assert not Passkey.objects.filter(user=gp_user).exists()


def test_the_register_step_checks_too(gp_client, gp_user):
    """Options fetched while the session was fresh do not carry a stale one
    through: the save is checked as well."""
    auth = SoftAuthenticator()
    options = _post_json(gp_client, REG_OPTIONS).json()
    _stale(gp_client)
    resp = _post_json(gp_client, REGISTER, {"credential": auth.create(options), "name": "x"})
    assert resp.status_code == 403
    assert not Passkey.objects.filter(user=gp_user).exists()


def test_typing_the_password_again_allows_it(gp_client, gp_user):
    _stale(gp_client)
    assert _enrol(gp_client, SoftAuthenticator(), password="pw").status_code == 200
    assert Passkey.objects.filter(user=gp_user).count() == 1


def test_a_wrong_password_is_refused(gp_client, gp_user):
    _stale(gp_client)
    resp = _post_json(gp_client, REG_OPTIONS, {"password": "not-it"})
    assert resp.status_code == 403
    assert resp.json()["error"] == "That password isn't right."
    # and the session is no fresher for it
    assert 'name="password"' in gp_client.get("/accounts/account/").content.decode()


@override_settings(AXES_ENABLED=True,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
def test_wrong_passwords_here_count_towards_the_login_lockout(gp_client, gp_user):
    """Otherwise a borrowed session would be an unlimited password-guessing
    oracle: it goes through authenticate(), as the login page does."""
    from axes.models import AccessAttempt
    _stale(gp_client)
    for g in range(5):
        _post_json(gp_client, REG_OPTIONS, {"password": f"guess-{g}"})
    assert AccessAttempt.objects.filter(username=gp_user.email).exists()
    resp = _post_json(gp_client, REG_OPTIONS, {"password": "pw"})
    assert resp.status_code == 429
    assert resp.json()["error"] == "Too many wrong attempts. Try again in an hour."


def test_changing_the_password_counts_as_proving_it(gp_client):
    _stale(gp_client)
    resp = gp_client.post("/accounts/password_change/", {
        "old_password": "pw", "new_password1": NEW_PW, "new_password2": NEW_PW})
    assert resp.status_code == 302
    assert _enrol(gp_client, SoftAuthenticator()).status_code == 200


# --- the pages ---------------------------------------------------------------------

def test_the_account_page_asks_for_the_password_only_when_it_will_be_needed(gp_client):
    fresh = gp_client.get("/accounts/account/").content.decode()
    assert 'name="password"' not in fresh
    _stale(gp_client)
    stale = gp_client.get("/accounts/account/").content.decode()
    assert 'name="password"' in stale and 'autocomplete="current-password"' in stale


def test_the_nudge_is_offered_only_just_after_signing_in(gp_client):
    assert 'id="passkey-nudge"' in gp_client.get("/accounts/account/").content.decode()
    _stale(gp_client)
    assert 'id="passkey-nudge"' not in gp_client.get("/accounts/account/").content.decode()


def test_signing_in_by_any_route_starts_the_window(gp_user):
    """The receiver is on user_logged_in, so the password form, a passkey
    and a password link all count."""
    c = Client()
    c.post("/accounts/login/", {"username": gp_user.email, "password": "pw"})
    assert isinstance(c.session.get("rota_auth_at"), int)


# --- telling the owner ---------------------------------------------------------------

def test_the_owner_is_emailed_when_a_passkey_is_added(gp_client, gp_user, configured):
    mail.outbox.clear()
    assert _enrol(gp_client, SoftAuthenticator(), name="Reception PC").status_code == 200
    (msg,) = mail.outbox
    assert msg.to == [gp_user.email]
    assert "passkey" in msg.subject.lower()
    assert '"Reception PC"' in msg.body
    assert "http://testserver/accounts/password_reset/" in msg.body
    assert "Also remove all my passkeys" in msg.body


def test_no_relay_means_no_email_and_no_error(gp_client):
    mail.outbox.clear()
    assert _enrol(gp_client, SoftAuthenticator()).status_code == 200
    assert mail.outbox == []


class _Broken(Locmem):
    def send_messages(self, messages):
        raise OSError("relay down")


def test_a_failed_notice_does_not_undo_the_passkey(gp_client, gp_user, configured, settings):
    settings.EMAIL_BACKEND = f"{__name__}._Broken"
    assert _enrol(gp_client, SoftAuthenticator()).status_code == 200
    assert Passkey.objects.filter(user=gp_user).count() == 1


# --- taking them back with a reset ---------------------------------------------------

def _reset_form(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    c = Client()
    resp = c.get(f"/accounts/reset/{uid}/{token}/")
    return c, resp["Location"]


def test_the_reset_form_offers_removal_only_to_an_account_with_passkeys(gp_client, gp_user):
    c, url = _reset_form(gp_user)
    assert "remove_passkeys" not in c.get(url).content.decode()
    _enrol(gp_client, SoftAuthenticator())
    c, url = _reset_form(gp_user)
    assert "Also remove all my passkeys" in c.get(url).content.decode()


def test_ticking_it_removes_every_passkey_and_they_stop_working(gp_client, gp_user):
    thief = SoftAuthenticator()
    _enrol(gp_client, thief, name="not mine")
    _enrol(gp_client, SoftAuthenticator(), name="mine")
    c, url = _reset_form(gp_user)
    resp = c.post(url, {"new_password1": NEW_PW, "new_password2": NEW_PW,
                        "remove_passkeys": "on"}, follow=True)
    assert "every passkey removed" in resp.content.decode()
    assert not Passkey.objects.filter(user=gp_user).exists()
    anon = Client()
    options = _post_json(anon, LOGIN_OPTIONS).json()
    assert _post_json(anon, LOGIN, {"credential": thief.get(options)}).status_code == 400


def test_leaving_it_keeps_them(gp_client, gp_user):
    _enrol(gp_client, SoftAuthenticator())
    c, url = _reset_form(gp_user)
    assert c.post(url, {"new_password1": NEW_PW, "new_password2": NEW_PW}).status_code == 302
    assert Passkey.objects.filter(user=gp_user).count() == 1
