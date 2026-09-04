"""Anyone can ask for a link; the link sets a password and signs them in.
These pin the public form (what it sends, what it never reveals), the
throttle, and the set-password page in both its voices."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core import mail

pytestmark = pytest.mark.django_db
User = get_user_model()
RESET = "/accounts/password_reset/"
DONE = "/accounts/password_reset/done/"
STRONG = "orchard-lantern-quiet-42"


@pytest.fixture
def configured(settings):
    settings.EMAIL_HOST = "smtp.example"
    settings.DEFAULT_FROM_EMAIL = "rota@example.org"


def _link_for(client, user):
    """Ask the public form for a link and read it out of the outbox — the
    same path a real person takes."""
    client.post(RESET, {"email": user.email})
    link = next(w for w in mail.outbox[-1].body.split() if w.startswith("http"))
    return link.replace("http://testserver", "")


def _form_url(client, link):
    """GET the emailed link. For a good token Django moves it into the
    session and redirects to a URL without it — that URL is where the form
    lives. A bad token renders "no longer valid" in place with no redirect,
    so the second value is then just the link itself."""
    resp = client.get(link, follow=True)
    return resp, (resp.redirect_chain[-1][0] if resp.redirect_chain else link)


# --- asking ------------------------------------------------------------------

def test_the_login_page_offers_the_way_back_in(client):
    html = client.get("/accounts/login/").content.decode()
    assert 'href="/accounts/password_reset/"' in html
    assert "Forgotten your password?" in html


def test_the_request_page_is_the_apps_own(client):
    resp = client.get(RESET)
    html = resp.content.decode()
    assert resp.status_code == 200
    assert "auth-card" in html and "Forgotten your password?" in html
    assert 'name="email"' in html
    assert "admin/base" not in [t.name for t in resp.templates]


def test_a_known_address_gets_a_reset_link(client, configured, gp_user):
    resp = client.post(RESET, {"email": "GP@example.com"})       # case-insensitive
    assert resp.status_code == 302 and resp["Location"] == DONE
    assert len(mail.outbox) == 1
    assert mail.outbox[0].subject == "Reset your Practice Rota password"
    assert "ask a rota admin" in mail.outbox[0].body


def test_an_unset_account_gets_an_invitation_instead(client, configured):
    User.objects.create_user(email="invited@example.com")
    client.post(RESET, {"email": "invited@example.com"})
    assert mail.outbox[0].subject == "Set up your Practice Rota login"


@pytest.mark.parametrize("email", ["nobody@example.com", "inactive@example.com"])
def test_unknown_and_inactive_addresses_send_nothing_and_look_the_same(client, configured, email):
    User.objects.create_user(email="inactive@example.com", password="pw", is_active=False)
    resp = client.post(RESET, {"email": email})
    assert resp.status_code == 302 and resp["Location"] == DONE
    assert mail.outbox == []


def test_the_done_page_promises_nothing_specific(client):
    html = client.get(DONE).content.decode()
    assert "Check your email" in html and "auth-card" in html


def test_a_second_request_within_five_minutes_is_quiet(client, configured, gp_user):
    client.post(RESET, {"email": gp_user.email})
    client.post(RESET, {"email": gp_user.email})
    assert len(mail.outbox) == 1
    gp_user.refresh_from_db()
    gp_user.password_link_sent_at -= timedelta(minutes=6)
    gp_user.save()
    client.post(RESET, {"email": gp_user.email})
    assert len(mail.outbox) == 2


def test_without_a_relay_the_public_form_never_shows_a_link(client, settings, gp_user):
    """The admin's fallback — the link on screen — must never happen here:
    this page is public, and the link is the password."""
    settings.EMAIL_HOST = ""
    resp = client.post(RESET, {"email": gp_user.email}, follow=True)
    assert mail.outbox == []
    assert "/accounts/reset/" not in resp.content.decode()
    gp_user.refresh_from_db()
    assert gp_user.password_link_sent_at is None


# --- the link ----------------------------------------------------------------

def test_an_invitation_link_welcomes_sets_the_password_and_signs_in(client, configured):
    user = User.objects.create_user(email="invited@example.com")
    link = _link_for(client, user)
    resp, form_url = _form_url(client, link)
    html = resp.content.decode()
    assert form_url.endswith("/set-password/")
    assert "Welcome" in html and "choose a password" in html
    assert 'name="new_password1"' in html and "auth-card" in html

    resp = client.post(form_url, {"new_password1": STRONG, "new_password2": STRONG})
    assert resp.status_code == 302 and resp["Location"] == "/rota/"
    assert client.session["_auth_user_id"] == str(user.pk)
    user.refresh_from_db()
    assert user.check_password(STRONG)


def test_a_reset_link_speaks_of_a_new_password(client, configured, gp_user):
    resp, _ = _form_url(client, _link_for(client, gp_user))
    html = resp.content.decode()
    assert "Choose a new password" in html and "Welcome" not in html


def test_a_used_link_is_refused(client, configured):
    user = User.objects.create_user(email="invited@example.com")
    link = _link_for(client, user)
    _, form_url = _form_url(client, link)
    client.post(form_url, {"new_password1": STRONG, "new_password2": STRONG})
    client.logout()
    resp, _ = _form_url(client, link)
    html = resp.content.decode()
    assert "no longer valid" in html and 'href="/accounts/password_reset/"' in html
    assert 'name="new_password1"' not in html


def test_an_expired_link_is_refused(client, configured, settings, gp_user):
    link = _link_for(client, gp_user)
    settings.PASSWORD_RESET_TIMEOUT = -1
    resp, _ = _form_url(client, link)
    assert "no longer valid" in resp.content.decode()


def test_a_deactivated_accounts_link_is_refused(client, configured, gp_user):
    link = _link_for(client, gp_user)
    gp_user.is_active = False
    gp_user.save()
    resp, _ = _form_url(client, link)
    assert "no longer valid" in resp.content.decode()
    assert "_auth_user_id" not in client.session


def test_a_garbage_link_is_refused_not_crashed(client):
    resp = client.get("/accounts/reset/not-a-uid/not-a-token/")
    assert resp.status_code == 200 and "no longer valid" in resp.content.decode()


def test_the_password_rules_apply(client, configured):
    user = User.objects.create_user(email="invited@example.com")
    _, form_url = _form_url(client, _link_for(client, user))
    resp = client.post(form_url, {"new_password1": "password", "new_password2": "password"})
    assert resp.status_code == 200 and "too common" in resp.content.decode()
    user.refresh_from_db()
    assert not user.has_usable_password()


# --- the Account page and changing a password while signed in ----------------

def test_the_account_page_needs_a_login(client):
    resp = client.get("/accounts/account/")
    assert resp.status_code == 302 and resp["Location"].startswith("/accounts/login/?next=")


def test_the_account_page_shows_the_email_and_the_way_to_change_the_password(gp_client):
    html = gp_client.get("/accounts/account/").content.decode()
    assert "gp@example.com" in html and 'href="/accounts/password_change/"' in html


def test_the_signed_in_email_links_to_the_account_page(gp_client):
    from rota.models import PracticeSettings
    PracticeSettings.load()
    html = gp_client.get("/rota/").content.decode()
    assert html.count('href="/accounts/account/"') == 2   # header, and the tab bar's More sheet


def test_the_change_form_is_the_apps_own(gp_client):
    html = gp_client.get("/accounts/password_change/").content.decode()
    assert "auth-card" in html and 'name="old_password"' in html


def test_changing_the_password_keeps_you_signed_in_and_says_so(gp_client, gp_user):
    resp = gp_client.post("/accounts/password_change/", {
        "old_password": "pw", "new_password1": STRONG, "new_password2": STRONG}, follow=True)
    assert resp.redirect_chain[-1][0] == "/accounts/account/"
    html = resp.content.decode()
    assert "Password changed." in html
    assert resp.wsgi_request.user.is_authenticated
    gp_user.refresh_from_db()
    assert gp_user.check_password(STRONG)


def test_the_old_change_done_route_is_gone(gp_client):
    assert gp_client.get("/accounts/password_change/done/").status_code == 404
