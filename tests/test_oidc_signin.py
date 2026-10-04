import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from accounts.models import Passkey
from accounts.oidc import PracticeAccountBackend

User = get_user_model()

ONLY_HR = "Sign in with the practice account."


@pytest.fixture
def oidc_on(settings):
    settings.PRACTICE_HR_URL = "https://hr.example"
    settings.OIDC_RP_CLIENT_ID = "abc"


# --- the login page: the practice account, and nothing else -------------------------

def test_login_page_offers_only_the_practice_account_when_configured(client, oidc_on):
    body = client.get("/accounts/login/").content.decode()
    assert "Sign in with the practice account" in body
    assert "/oidc/authenticate/" in body
    assert 'id="login-form"' not in body and 'name="password"' not in body
    assert "auth-local" not in body and "Rota password" not in body
    assert "/accounts/password_reset/" not in body and "Forgotten your password?" not in body
    assert 'id="passkey-login"' not in body and "/accounts/passkeys/" not in body


def test_login_page_as_before_when_not_configured(client, settings):
    settings.PRACTICE_HR_URL = ""
    body = client.get("/accounts/login/").content.decode()
    assert "practice account" not in body
    assert "auth-local" not in body and 'id="login-form"' in body
    assert 'id="passkey-login"' in body
    assert 'href="/accounts/password_reset/"' in body


# --- no rota password for anyone, the superuser included ----------------------------

def _password_login(client, email, password="pw"):
    return client.post("/accounts/login/", {"username": email, "password": password})


def test_with_the_practice_account_nobody_uses_a_password(client, oidc_on, db):
    User.objects.create_user(email="gp@example.org", password="pw")
    User.objects.create_superuser(email="root@example.org", password="pw")
    for email in ("gp@example.org", "root@example.org", "Root@example.org"):
        r = _password_login(client, email)
        assert r.status_code == 200 and "_auth_user_id" not in client.session


def test_the_refusal_says_where_to_go(client, oidc_on, db):
    User.objects.create_user(email="gp@example.org", password="pw")
    User.objects.create_superuser(email="root@example.org", password="pw")
    # Right, wrong, the superuser's, and an address with no account all read
    # the same, so the form tells nobody which addresses have rota accounts.
    for email, password in (("gp@example.org", "pw"), ("gp@example.org", "wrong"),
                            ("root@example.org", "pw"), ("nobody@example.org", "pw")):
        body = _password_login(client, email, password).content.decode()
        assert ONLY_HR in body
        assert 'name="password"' not in body


def test_the_form_refuses_before_any_password_is_checked(oidc_on, db, rf, monkeypatch):
    """The login form, not a backend: authenticate() never runs, so nothing
    reaches the lockout's counters."""
    from django.contrib import auth

    from accounts.views import PRACTICE_ACCOUNT_ONLY, LoginForm
    assert PRACTICE_ACCOUNT_ONLY == ONLY_HR
    User.objects.create_user(email="gp@example.org", password="pw")
    User.objects.create_superuser(email="root@example.org", password="pw")
    calls = []
    monkeypatch.setattr("django.contrib.auth.forms.authenticate",
                        lambda *a, **k: calls.append(k) or auth.authenticate(*a, **k))
    for email in ("GP@example.org", "root@example.org"):
        form = LoginForm(rf.post("/accounts/login/"), data={"username": email,
                                                              "password": "pw"})
        assert not form.is_valid() and form.non_field_errors() == [ONLY_HR]
    assert calls == []


@override_settings(AXES_ENABLED=True,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
def test_staff_typing_their_right_passwords_do_not_lock_the_surgery_out(oidc_on, db):
    """The re-review's probe of the backend this replaced: five staff each
    typing their own right rota password once from the surgery counted as
    five failures against five accounts, and locked the address — and the
    practice-account callback with it — for an hour."""
    from axes.models import AccessAttempt, AccessFailureLog
    surgery = {"REMOTE_ADDR": "127.0.0.1", "HTTP_CF_CONNECTING_IP": "203.0.113.10"}
    for i in range(5):
        User.objects.create_user(email=f"gp{i}@example.org", password="pw")
        r = Client().post("/accounts/login/", {"username": f"gp{i}@example.org",
                                               "password": "pw"}, **surgery)
        assert r.status_code == 200
    assert not AccessAttempt.objects.exists() and not AccessFailureLog.objects.exists()


@override_settings(AXES_ENABLED=True,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
def test_the_superusers_password_is_refused_without_counting(oidc_on, db):
    from axes.models import AccessAttempt, AccessFailureLog
    User.objects.create_superuser(email="root@example.org", password="pw")
    for password in ("pw", "no"):
        r = Client().post("/accounts/login/", {"username": "root@example.org",
                                               "password": password})
        assert r.status_code == 200 and ONLY_HR in r.content.decode()
    assert not AccessAttempt.objects.exists() and not AccessFailureLog.objects.exists()


@override_settings(AXES_ENABLED=True,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
def test_without_the_practice_account_a_wrong_password_still_counts(settings, db):
    """Break-glass: with PRACTICE_HR_URL removed, the password form is back,
    lockout and all."""
    from axes.models import AccessAttempt
    settings.PRACTICE_HR_URL = ""
    User.objects.create_superuser(email="root@example.org", password="pw")
    Client().post("/accounts/login/", {"username": "root@example.org", "password": "no"})
    assert AccessAttempt.objects.filter(username="root@example.org").exists()
    assert Client().post("/accounts/login/", {"username": "root@example.org",
                                              "password": "pw"}).status_code == 302


def test_password_allowed_is_false_for_everyone(oidc_on, db, settings):
    from accounts.recent_auth import password_allowed
    gp = User.objects.create_user(email="gp@example.org", password="pw")
    root = User.objects.create_superuser(email="root@example.org", password="pw")
    assert not password_allowed(gp) and not password_allowed(root)
    settings.PRACTICE_HR_URL = ""
    assert password_allowed(gp) and password_allowed(root)


# --- passkeys are retired while the practice account is on --------------------------

PASSKEY_ENDPOINTS = ("/accounts/passkeys/login/options/", "/accounts/passkeys/login/",
                     "/accounts/passkeys/register/options/", "/accounts/passkeys/register/")


@pytest.mark.parametrize("url", PASSKEY_ENDPOINTS)
def test_the_passkey_endpoints_are_gone(client, oidc_on, db, url):
    client.force_login(User.objects.create_superuser(email="root@example.org", password="pw"))
    assert client.post(url, data="{}", content_type="application/json").status_code == 404
    assert Client().post(url, data="{}", content_type="application/json").status_code == 404


@pytest.mark.parametrize("url", PASSKEY_ENDPOINTS)
def test_without_the_practice_account_the_passkey_endpoints_answer(client, settings, db, url):
    settings.PRACTICE_HR_URL = ""
    client.force_login(User.objects.create_user(email="gp@example.org", password="pw"))
    assert client.post(url, data="{}", content_type="application/json").status_code != 404


@override_settings(AXES_ENABLED=True,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
def test_a_password_sent_to_add_a_passkey_is_never_checked(gp_client, oidc_on):
    import json

    from axes.models import AccessAttempt, AccessFailureLog
    r = gp_client.post("/accounts/passkeys/register/options/",
                       data=json.dumps({"password": "wrong"}), content_type="application/json")
    assert r.status_code == 404
    assert not AccessAttempt.objects.exists() and not AccessFailureLog.objects.exists()


ACCOUNT_SENTENCE = ("You sign in with the practice account. Passwords and passkeys are "
                    "managed on the HR system.")


def _text(html):
    import re
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html))


def test_the_account_page_points_to_the_hr_system(client, oidc_on, db):
    root = User.objects.create_superuser(email="root@example.org", password="pw")
    Passkey.objects.create(user=root, credential_id="abc", public_key="k", name="My phone")
    client.force_login(root)
    body = client.get("/accounts/account/").content.decode()
    assert ACCOUNT_SENTENCE in _text(body)
    assert 'href="https://hr.example/accounts/account/"' in body
    assert "Change password" not in body and "/accounts/password_change/" not in body
    assert "<h2>Passkeys</h2>" not in body and "My phone" not in body
    assert 'id="passkey-add"' not in body
    # Left in place: they work again if the setting is removed.
    assert Passkey.objects.filter(user=root).exists()


def test_without_the_practice_account_the_account_page_is_as_before(gp_client, settings):
    settings.PRACTICE_HR_URL = ""
    body = gp_client.get("/accounts/account/").content.decode()
    assert "Change password" in body and "<h2>Passkeys</h2>" in body
    assert "managed on the HR system" not in body


def test_no_offer_to_add_a_passkey_after_signing_in(client, oidc_on, db):
    client.force_login(User.objects.create_user(email="gp@example.org", password="pw"))
    assert 'id="passkey-nudge"' not in client.get("/", follow=True).content.decode()


def test_without_the_practice_account_the_offer_is_made(client, settings, db):
    settings.PRACTICE_HR_URL = ""
    client.force_login(User.objects.create_user(email="gp@example.org", password="pw"))
    assert 'id="passkey-nudge"' in client.get("/", follow=True).content.decode()


# --- password links work for nobody ---------------------------------------------------

def _link(user):
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return f"/accounts/reset/{uid}/{default_token_generator.make_token(user)}/"


def test_the_reset_form_sends_nobody_anything(client, oidc_on, db, configured):
    from django.core import mail
    User.objects.create_user(email="gp@example.org", password="pw")
    User.objects.create_superuser(email="root@example.org", password="pw")
    mail.outbox.clear()
    for email in ("gp@example.org", "root@example.org"):
        assert client.post("/accounts/password_reset/", {"email": email}).status_code == 302
    assert mail.outbox == []


def test_without_the_practice_account_the_reset_form_sends(client, settings, db, configured):
    from django.core import mail
    settings.PRACTICE_HR_URL = ""
    User.objects.create_user(email="gp@example.org", password="pw")
    mail.outbox.clear()
    client.post("/accounts/password_reset/", {"email": "gp@example.org"})
    assert [m.to for m in mail.outbox] == [["gp@example.org"]]


def test_a_staff_link_opens_the_invalid_link_page(client, oidc_on, db):
    """A link sent before PRACTICE_HR_URL was set, or an admin's invitation,
    would otherwise sign them straight in, around the HR system."""
    gp = User.objects.create_user(email="gp@example.org", password="pw")
    r = client.get(_link(gp), follow=True)
    assert "This link is no longer valid" in r.content.decode()
    assert "_auth_user_id" not in client.session


def test_an_invitation_for_staff_is_refused_too(client, oidc_on, db):
    gp = User.objects.create_user(email="new@example.org")      # no usable password
    r = client.get(_link(gp), follow=True)
    assert "This link is no longer valid" in r.content.decode()


def test_the_superusers_link_is_refused_too(client, oidc_on, db):
    root = User.objects.create_superuser(email="root@example.org", password="pw")
    r = client.get(_link(root), follow=True)
    assert "This link is no longer valid" in r.content.decode()
    assert "_auth_user_id" not in client.session


def test_without_the_practice_account_staff_links_work(client, settings, db):
    settings.PRACTICE_HR_URL = ""
    gp = User.objects.create_user(email="gp@example.org", password="pw")
    assert "Choose a new password" in client.get(_link(gp), follow=True).content.decode()


def test_without_the_practice_account_passwords_work_as_before(client, settings, db):
    settings.PRACTICE_HR_URL = ""
    User.objects.create_user(email="gp@example.org", password="pw")
    assert _password_login(client, "gp@example.org").status_code == 302


def test_existing_user_matched_by_case_insensitive_email(db):
    u = User.objects.create_user(email="Tom@Example.org", password="pw")
    found = PracticeAccountBackend().filter_users_by_claims({"email": "tom@example.org"})
    assert list(found) == [u]


def test_new_user_created_without_password_and_not_admin(db):
    b = PracticeAccountBackend()
    u = b.create_user({"email": "new@example.org", "employee_id": 7})
    assert not u.has_usable_password() and not u.is_rota_admin and u.is_active


def test_no_email_claim_matches_nobody(db):
    assert list(PracticeAccountBackend().filter_users_by_claims({})) == []


# --- who a sign-in is: sub once seen, the superuser too (review I9) -----------------

from django.core.exceptions import SuspiciousOperation  # noqa: E402


def _sign_in(claims, monkeypatch):
    """The backend's matching, as mozilla-django-oidc runs it after the code
    exchange, with the userinfo response standing in for the HR system."""
    b = PracticeAccountBackend()
    monkeypatch.setattr(b, "get_userinfo", lambda *a: claims)
    return b.get_or_create_user("access", "id", {})


def test_the_first_sign_in_binds_the_sub(db, monkeypatch):
    u = User.objects.create_user(email="tom@example.org", password="pw")
    assert _sign_in({"sub": "12", "email": "Tom@Example.org"}, monkeypatch) == u
    u.refresh_from_db()
    assert u.oidc_sub == "12"


def test_later_sign_ins_match_on_sub_whatever_the_email_says(db, monkeypatch):
    u = User.objects.create_user(email="tom@example.org", password="pw", oidc_sub="12")
    assert _sign_in({"sub": "12", "email": "tom.hodges@example.org"}, monkeypatch) == u
    assert User.objects.count() == 1


def test_an_edited_email_on_the_hr_side_cannot_take_over_a_bound_account(db, monkeypatch):
    """An HR admin changes another HR login's email to a rota admin's: the
    rota admin is bound to their own sub, so the email match is refused,
    and no second account is made for the address."""
    admin = User.objects.create_user(email="boss@example.org", password="pw",
                                     is_rota_admin=True, oidc_sub="1")
    with pytest.raises(SuspiciousOperation):
        _sign_in({"sub": "99", "email": "boss@example.org", "admin": True}, monkeypatch)
    assert list(User.objects.all()) == [admin]
    admin.refresh_from_db()
    assert admin.oidc_sub == "1"


def test_the_superuser_signs_in_with_the_practice_account(db, monkeypatch):
    root = User.objects.create_superuser(email="root@example.org", password="pw")
    assert _sign_in({"sub": "5", "email": "Root@example.org", "admin": True},
                    monkeypatch) == root
    root.refresh_from_db()
    assert root.oidc_sub == "5" and root.is_superuser and User.objects.count() == 1


def test_and_is_matched_on_the_sub_after_that(db, monkeypatch):
    root = User.objects.create_superuser(email="root@example.org", password="pw", oidc_sub="5")
    assert list(PracticeAccountBackend().filter_users_by_claims(
        {"sub": "5", "email": "someone.else@example.org"})) == [root]


def test_a_superuser_bound_to_one_sub_cannot_be_taken_by_another(db, monkeypatch):
    root = User.objects.create_superuser(email="root@example.org", password="pw", oidc_sub="5")
    with pytest.raises(SuspiciousOperation):
        _sign_in({"sub": "6", "email": "root@example.org"}, monkeypatch)
    root.refresh_from_db()
    assert root.oidc_sub == "5"


def test_a_new_person_is_created_bound_to_their_sub(db, monkeypatch):
    u = _sign_in({"sub": "40", "email": "new@example.org"}, monkeypatch)
    assert u.email == "new@example.org" and u.oidc_sub == "40"
    assert not u.has_usable_password() and not u.is_rota_admin and not u.is_superuser


# --- rota admin is the HR system's `admin` claim ------------------------------------

def test_a_new_person_with_the_admin_claim_is_a_rota_admin(db, monkeypatch):
    u = _sign_in({"sub": "40", "email": "new@example.org", "admin": True}, monkeypatch)
    u.refresh_from_db()
    assert u.is_rota_admin and u.is_staff


def test_rota_admin_follows_the_claim_both_ways(db, monkeypatch):
    u = User.objects.create_user(email="tom@example.org", password="pw", oidc_sub="12")
    _sign_in({"sub": "12", "email": "tom@example.org", "admin": True}, monkeypatch)
    u.refresh_from_db()
    assert u.is_rota_admin and u.is_staff
    _sign_in({"sub": "12", "email": "tom@example.org", "admin": False}, monkeypatch)
    u.refresh_from_db()
    assert not u.is_rota_admin and not u.is_staff


def test_a_missing_claim_reads_as_not_an_admin(db, monkeypatch):
    """An HR system older than the claim says nothing about it: no admin."""
    u = User.objects.create_user(email="boss@example.org", password="pw", oidc_sub="12",
                                 is_rota_admin=True)
    _sign_in({"sub": "12", "email": "boss@example.org"}, monkeypatch)
    u.refresh_from_db()
    assert not u.is_rota_admin and not u.is_staff
    assert not _sign_in({"sub": "41", "email": "new@example.org"}, monkeypatch).is_rota_admin


@pytest.mark.parametrize("claim", [None, "true", "false", 1])
def test_only_a_true_claim_makes_an_admin(db, monkeypatch, claim):
    u = _sign_in({"sub": "40", "email": "new@example.org", "admin": claim}, monkeypatch)
    assert not u.is_rota_admin


def test_the_superusers_rota_admin_follows_the_claim_too(db, monkeypatch):
    root = User.objects.create_superuser(email="root@example.org", password="pw", oidc_sub="5")
    _sign_in({"sub": "5", "email": "root@example.org", "admin": False}, monkeypatch)
    root.refresh_from_db()
    assert not root.is_rota_admin and root.is_superuser and root.is_staff


def test_nothing_is_saved_when_nothing_changed(db, monkeypatch):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    u = User.objects.create_user(email="tom@example.org", password="pw", oidc_sub="12",
                                 is_rota_admin=True)
    with CaptureQueriesContext(connection) as queries:
        _sign_in({"sub": "12", "email": "tom@example.org", "admin": True}, monkeypatch)
    assert not [q for q in queries if q["sql"].startswith("UPDATE")]
    u.refresh_from_db()
    assert u.is_rota_admin


def test_only_a_superuser_sees_the_binding(db, client, admin_client):
    """So a superuser can clear it when someone's HR login is replaced."""
    u = User.objects.create_user(email="tom@example.org", password="pw", oidc_sub="12")
    root = User.objects.create_superuser(email="root2@example.org", password="pw")
    client.force_login(root)
    assert 'name="oidc_sub"' in client.get(f"/admin/accounts/user/{u.pk}/change/").content.decode()
    assert 'name="oidc_sub"' not in admin_client.get(f"/admin/accounts/user/{u.pk}/change/").content.decode()


# --- the admin: rota admin is set on the HR system ----------------------------------

ADMIN_HELP = ("Set on the HR system: Login accounts › Apps › Admin of rota. It is updated "
              "at each sign-in.")


def _root_client(client):
    client.force_login(User.objects.create_superuser(email="root2@example.org", password="pw"))
    return client


def test_rota_admin_is_read_only_in_the_admin(db, client, oidc_on):
    u = User.objects.create_user(email="tom@example.org", password="pw")
    c = _root_client(client)
    body = c.get(f"/admin/accounts/user/{u.pk}/change/").content.decode()
    assert 'name="is_rota_admin"' not in body
    assert ADMIN_HELP in body
    c.post(f"/admin/accounts/user/{u.pk}/change/", {"email": u.email, "is_active": "on",
                                                     "is_rota_admin": "on"})
    u.refresh_from_db()
    assert not u.is_rota_admin


def test_the_add_form_drops_rota_admin(db, client, oidc_on):
    body = _root_client(client).get("/admin/accounts/user/add/").content.decode()
    assert 'name="email"' in body and 'name="is_rota_admin"' not in body


def test_without_the_practice_account_rota_admin_is_ticked_here(db, client, settings):
    settings.PRACTICE_HR_URL = ""
    u = User.objects.create_user(email="tom@example.org", password="pw")
    c = _root_client(client)
    body = c.get(f"/admin/accounts/user/{u.pk}/change/").content.decode()
    assert 'name="is_rota_admin"' in body and ADMIN_HELP not in body
    assert 'name="is_rota_admin"' in c.get("/admin/accounts/user/add/").content.decode()


# --- signing out signs out of the HR system too (review I7, rota half) ---------------

from urllib.parse import parse_qs, urlsplit  # noqa: E402


def test_logging_out_goes_on_to_the_hr_systems_sign_out(client, oidc_on, db):
    u = User.objects.create_user(email="gp@example.org", password="pw")
    client.force_login(u)
    session = client.session
    session["oidc_id_token"] = "the.id.token"
    session.save()
    r = client.post("/accounts/logout/")
    assert r.status_code == 302
    url = urlsplit(r["Location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://hr.example/o/logout/"
    assert parse_qs(url.query) == {
        "post_logout_redirect_uri": ["http://testserver/accounts/login/"],
        "client_id": ["abc"], "id_token_hint": ["the.id.token"]}
    assert "_auth_user_id" not in client.session
    assert r["Clear-Site-Data"] == '"cache"'


def test_without_an_id_token_the_hint_is_left_out(client, oidc_on, db):
    client.force_login(User.objects.create_superuser(email="root@example.org", password="pw"))
    r = client.post("/admin/logout/")
    query = parse_qs(urlsplit(r["Location"]).query)
    assert r["Location"].startswith("https://hr.example/o/logout/")
    assert "id_token_hint" not in query and query["client_id"] == ["abc"]


def test_without_the_practice_account_logout_is_unchanged(client, settings, db):
    settings.PRACTICE_HR_URL = ""
    client.force_login(User.objects.create_user(email="gp@example.org", password="pw"))
    assert client.post("/accounts/logout/")["Location"] == "/accounts/login/"


def test_the_id_token_is_kept_for_sign_out(settings):
    assert settings.OIDC_STORE_ID_TOKEN is True


def test_the_policy_lets_the_sign_out_form_redirect_to_the_hr_system(client, oidc_on, db):
    """Browsers apply form-action to the redirects after a form post."""
    client.force_login(User.objects.create_user(email="gp@example.org", password="pw"))
    policy = client.get("/accounts/account/")["Content-Security-Policy"]
    assert "form-action 'self' https://hr.example;" in policy
