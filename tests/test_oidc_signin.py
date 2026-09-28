import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from accounts.oidc import PracticeAccountBackend

User = get_user_model()


@pytest.fixture
def oidc_on(settings):
    settings.PRACTICE_HR_URL = "https://hr.example"
    settings.OIDC_RP_CLIENT_ID = "abc"


def test_login_page_offers_practice_account_when_configured(client, oidc_on):
    body = client.get("/accounts/login/").content.decode()
    assert "Sign in with the practice account" in body
    assert "/oidc/authenticate/" in body


def test_login_page_silent_when_not_configured(client, settings):
    settings.PRACTICE_HR_URL = ""
    body = client.get("/accounts/login/").content.decode()
    assert "practice account" not in body
    assert "auth-local" not in body and 'id="login-form"' in body


# --- the rota's password is the superuser's alone (review I8) -------------------------

def test_the_password_form_is_folded_away_for_superusers(client, oidc_on):
    body = client.get("/accounts/login/").content.decode()
    assert body.index("Sign in with the practice account") < body.index("<details")
    assert "<summary>Rota password (superusers only)</summary>" in body
    assert '<details class="auth-local">' in body, "closed until it has an error to show"
    assert body.index("<details") < body.index('id="login-form"') < body.index("</details>")


def _password_login(client, email, password="pw"):
    return client.post("/accounts/login/", {"username": email, "password": password})


def test_with_the_practice_account_only_a_superuser_uses_a_password(client, oidc_on, db):
    User.objects.create_user(email="gp@example.org", password="pw")
    r = _password_login(client, "gp@example.org")
    assert r.status_code == 200 and "_auth_user_id" not in client.session
    assert '<details class="auth-local" open>' in r.content.decode()
    User.objects.create_superuser(email="root@example.org", password="pw")
    assert _password_login(client, "Root@example.org").status_code == 302


def test_the_refusal_says_where_to_go(client, oidc_on, db):
    User.objects.create_user(email="gp@example.org", password="pw")
    for password in ("pw", "wrong"):
        body = _password_login(client, "gp@example.org", password).content.decode()
        assert ("Sign in with the practice account; the rota password is for the "
                "superuser only.") in body
    # An address with no account reads the same, so the form tells nobody
    # which addresses have rota accounts.
    assert "the rota password is for the superuser only." in _password_login(
        client, "nobody@example.org").content.decode()


def test_the_form_refuses_before_any_password_is_checked(oidc_on, db, rf, monkeypatch):
    """The login form, not a backend: authenticate() never runs for anyone
    but the superuser, so nothing reaches the lockout's counters."""
    from django.contrib import auth

    from accounts.views import LoginForm
    User.objects.create_user(email="gp@example.org", password="pw")
    calls = []
    monkeypatch.setattr("django.contrib.auth.forms.authenticate",
                        lambda *a, **k: calls.append(k) or auth.authenticate(*a, **k))
    form = LoginForm(rf.post("/accounts/login/"), data={"username": "GP@example.org",
                                                          "password": "pw"})
    assert not form.is_valid() and form.non_field_errors()[0].startswith(
        "Sign in with the practice account")
    assert calls == []
    User.objects.create_superuser(email="root@example.org", password="pw")
    form = LoginForm(rf.post("/accounts/login/"), data={"username": "root@example.org",
                                                          "password": "pw"})
    assert form.is_valid() and len(calls) == 1


@override_settings(AXES_ENABLED=True,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
def test_staff_typing_their_right_passwords_do_not_lock_the_surgery_out(oidc_on, db):
    """The re-review's probe of the backend this replaced: five staff each
    typing their own right rota password once from the surgery counted as
    five failures against five accounts, and locked the address — the
    superuser and the practice-account callback with it — for an hour."""
    from axes.models import AccessAttempt, AccessFailureLog
    surgery = {"REMOTE_ADDR": "127.0.0.1", "HTTP_CF_CONNECTING_IP": "203.0.113.10"}
    for i in range(5):
        User.objects.create_user(email=f"gp{i}@example.org", password="pw")
        r = Client().post("/accounts/login/", {"username": f"gp{i}@example.org",
                                               "password": "pw"}, **surgery)
        assert r.status_code == 200
    assert not AccessAttempt.objects.exists() and not AccessFailureLog.objects.exists()
    User.objects.create_superuser(email="root@example.org", password="pw")
    r = Client().post("/accounts/login/", {"username": "root@example.org", "password": "pw"},
                      **surgery)
    assert r.status_code == 302


@override_settings(AXES_ENABLED=True,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
def test_the_superusers_wrong_password_still_counts(oidc_on, db):
    from axes.models import AccessAttempt
    User.objects.create_superuser(email="root@example.org", password="pw")
    Client().post("/accounts/login/", {"username": "root@example.org", "password": "no"})
    assert AccessAttempt.objects.filter(username="root@example.org").exists()


# --- adding a passkey later needs the practice account, not a password ---------------

def _stale(client):
    import time

    from accounts import recent_auth
    session = client.session
    session["rota_auth_at"] = int(time.time()) - recent_auth.WINDOW - 1
    session.save()


def test_the_account_page_does_not_ask_staff_for_a_password(gp_client, oidc_on):
    _stale(gp_client)
    body = gp_client.get("/accounts/account/").content.decode()
    assert 'name="password"' not in body
    assert "sign in again with the practice account" in body


@override_settings(AXES_ENABLED=True,
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
def test_a_password_sent_anyway_is_refused_without_counting(gp_client, gp_user, oidc_on):
    import json

    from axes.models import AccessAttempt, AccessFailureLog
    _stale(gp_client)
    r = gp_client.post("/accounts/passkeys/register/options/", data=json.dumps({"password": "pw"}),
                       content_type="application/json")
    assert r.status_code == 403
    assert r.json() == {"error": "Sign in again with the practice account to add a passkey."}
    assert not AccessAttempt.objects.exists() and not AccessFailureLog.objects.exists()


def test_the_superuser_is_still_asked_for_the_password(client, oidc_on, db):
    client.force_login(User.objects.create_superuser(email="root@example.org", password="pw"))
    _stale(client)
    assert 'name="password"' in client.get("/accounts/account/").content.decode()


# --- password links are the superuser's alone too -------------------------------------

def _link(user):
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return f"/accounts/reset/{uid}/{default_token_generator.make_token(user)}/"


def test_the_reset_form_sends_staff_nothing(client, oidc_on, db, configured):
    from django.core import mail
    User.objects.create_user(email="gp@example.org", password="pw")
    User.objects.create_superuser(email="root@example.org", password="pw")
    mail.outbox.clear()
    assert client.post("/accounts/password_reset/", {"email": "gp@example.org"}).status_code == 302
    assert mail.outbox == []
    client.post("/accounts/password_reset/", {"email": "root@example.org"})
    assert [m.to for m in mail.outbox] == [["root@example.org"]]


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


def test_the_superusers_link_still_works(client, oidc_on, db):
    root = User.objects.create_superuser(email="root@example.org", password="pw")
    r = client.get(_link(root), follow=True)
    assert "Choose a new password" in r.content.decode()


def test_without_the_practice_account_staff_links_work(client, settings, db):
    settings.PRACTICE_HR_URL = ""
    gp = User.objects.create_user(email="gp@example.org", password="pw")
    assert "Choose a new password" in client.get(_link(gp), follow=True).content.decode()


def test_forgotten_password_is_inside_the_folded_section(client, oidc_on):
    body = client.get("/accounts/login/").content.decode()
    link = body.index('href="/accounts/password_reset/"')
    assert body.index("<details") < link < body.index("</details>")
    assert body.count('href="/accounts/password_reset/"') == 1


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


# --- who a sign-in is: sub once seen, never the superuser (review I9) ---------------

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
        _sign_in({"sub": "99", "email": "boss@example.org"}, monkeypatch)
    assert list(User.objects.all()) == [admin]
    admin.refresh_from_db()
    assert admin.oidc_sub == "1"


def test_the_superuser_is_never_signed_in_by_the_practice_account(db, monkeypatch):
    root = User.objects.create_superuser(email="root@example.org", password="pw")
    with pytest.raises(SuspiciousOperation):
        _sign_in({"sub": "5", "email": "root@example.org"}, monkeypatch)
    root.refresh_from_db()
    assert root.oidc_sub == "" and User.objects.count() == 1


def test_not_even_with_a_sub_stored_against_them(db, monkeypatch):
    User.objects.create_superuser(email="root@example.org", password="pw", oidc_sub="5")
    assert not PracticeAccountBackend().filter_users_by_claims(
        {"sub": "5", "email": "root@example.org"}).exists()


def test_a_new_person_is_created_bound_to_their_sub(db, monkeypatch):
    u = _sign_in({"sub": "40", "email": "new@example.org"}, monkeypatch)
    assert u.email == "new@example.org" and u.oidc_sub == "40"
    assert not u.has_usable_password() and not u.is_rota_admin and not u.is_superuser


def test_only_a_superuser_sees_the_binding(db, client, admin_client):
    """So a superuser can clear it when someone's HR login is replaced."""
    u = User.objects.create_user(email="tom@example.org", password="pw", oidc_sub="12")
    root = User.objects.create_superuser(email="root2@example.org", password="pw")
    client.force_login(root)
    assert 'name="oidc_sub"' in client.get(f"/admin/accounts/user/{u.pk}/change/").content.decode()
    assert 'name="oidc_sub"' not in admin_client.get(f"/admin/accounts/user/{u.pk}/change/").content.decode()


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
