"""An admin creates the account; the person sets the password from an
emailed link. These pin the add form, the state the change page shows, the
send buttons, the bulk action, and that a rota admin can no longer set
anyone's password directly — only a superuser keeps that form."""

import smtplib
from datetime import timedelta

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.mail import EmailMessage
from django.utils import timezone

pytestmark = pytest.mark.django_db
User = get_user_model()
ADD = "/admin/accounts/user/add/"
LIST = "/admin/accounts/user/"


def _change(user):
    return f"/admin/accounts/user/{user.pk}/change/"


def _form(user, **extra):
    """A change-form POST that leaves the account as it is. The System
    flags are only on a superuser's form; a rota admin's form ignores the
    extra keys (test_admin_site proves that). The passkeys-* fields are
    the PasskeyInline's management form — the change view needs them on
    every POST regardless of whether this user has any passkeys."""
    data = {"email": user.email,
            "is_rota_admin": "on" if user.is_rota_admin else "",
            "is_active": "on",
            "is_staff": "on" if user.is_staff else "",
            "is_superuser": "on" if user.is_superuser else "",
            "passkeys-TOTAL_FORMS": "0", "passkeys-INITIAL_FORMS": "0",
            "passkeys-MIN_NUM_FORMS": "0", "passkeys-MAX_NUM_FORMS": "1000"}
    data.update(extra)
    return data


def _user_admin():
    return admin.site._registry[User]


# --- adding -----------------------------------------------------------------

def test_the_add_form_asks_for_email_and_role_only(admin_client):
    html = admin_client.get(ADD).content.decode()
    assert 'name="email"' in html and 'name="is_rota_admin"' in html
    assert 'name="password1"' not in html and 'name="usable_password"' not in html


def test_adding_an_account_sends_an_invitation(admin_client, configured):
    resp = admin_client.post(ADD, {"email": "new@example.com", "is_rota_admin": "on"},
                             follow=True)
    user = User.objects.get(email="new@example.com")
    assert not user.has_usable_password() and user.is_rota_admin and not user.is_superuser
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["new@example.com"]
    assert mail.outbox[0].subject == "Set up your Practice Rota login"
    html = resp.content.decode()
    assert "Invitation sent to new@example.com" in html
    assert "Invited" in html and "link expires" in html   # landed on the change page


def test_without_a_relay_the_admin_gets_the_link_to_copy(admin_client, settings):
    settings.EMAIL_HOST = ""
    html = admin_client.post(ADD, {"email": "new@example.com"}, follow=True).content.decode()
    assert mail.outbox == []
    assert "copy this link and send it to new@example.com yourself" in html
    assert 'href="http://testserver/accounts/reset/' in html


def test_a_refusing_relay_shows_the_reason_and_the_link(admin_client, configured, monkeypatch):
    def refuse(self, fail_silently=False):
        raise smtplib.SMTPRecipientsRefused({"new@example.com": (550, b"no such user")})
    monkeypatch.setattr(EmailMessage, "send", refuse)
    html = admin_client.post(ADD, {"email": "new@example.com"}, follow=True).content.decode()
    assert "Sending to new@example.com failed" in html and "550" in html
    assert 'href="http://testserver/accounts/reset/' in html
    assert User.objects.filter(email="new@example.com").exists()   # the relay's refusal loses no account


# --- the state field ---------------------------------------------------------

def test_the_state_field_reads_the_account(settings, gp_user):
    settings.PASSWORD_RESET_TIMEOUT = 7 * 24 * 3600
    state = _user_admin().account_state
    assert state(gp_user) == "Set up"
    gp_user.password_link_sent_at = timezone.now()
    last = timezone.localtime(gp_user.password_link_sent_at)
    assert state(gp_user) == f"Set up — last link sent {last:%-d %b %H:%M}"
    invited = User.objects.create_user(email="invited@example.com")
    assert state(invited) == "Not yet invited"
    invited.password_link_sent_at = timezone.now()
    sent = timezone.localtime(invited.password_link_sent_at)
    expires = timezone.localtime(invited.password_link_sent_at + timedelta(days=7))
    assert state(invited) == f"Invited {sent:%-d %b}, link expires {expires:%-d %b}"
    invited.password_link_sent_at = timezone.now() - timedelta(days=8)
    assert state(invited) == "Invitation expired — send another"


def test_the_change_page_shows_the_state(admin_client, gp_user):
    html = admin_client.get(_change(gp_user)).content.decode()
    assert "Set up" in html and "Invited" not in html


def test_the_changelist_says_who_is_set_up(admin_client, gp_user):
    invited = User.objects.create_user(email="invited@example.com")
    is_set_up = _user_admin().is_set_up
    assert is_set_up(gp_user) is True and is_set_up(invited) is False
    assert "Set up?" in admin_client.get(LIST).content.decode()


# --- the buttons -------------------------------------------------------------

def test_the_submit_line_offers_the_right_button(admin_client, gp_user):
    html = admin_client.get(_change(gp_user)).content.decode()
    assert 'name="accounts_user_send_reset_link"' in html
    assert 'name="accounts_user_send_invitation"' not in html
    assert "Send password-reset link" in html
    invited = User.objects.create_user(email="invited@example.com")
    html = admin_client.get(_change(invited)).content.decode()
    assert 'name="accounts_user_send_invitation"' in html
    assert 'name="accounts_user_send_reset_link"' not in html
    assert "Send invitation again" in html


def test_pressing_the_button_sends(admin_client, configured, gp_user):
    resp = admin_client.post(_change(gp_user), _form(gp_user, accounts_user_send_reset_link="1"),
                             follow=True)
    assert len(mail.outbox) == 1
    assert mail.outbox[0].subject == "Reset your Practice Rota password"
    assert "Password-reset link sent to gp@example.com" in resp.content.decode()

    invited = User.objects.create_user(email="invited@example.com")
    admin_client.post(_change(invited), _form(invited, accounts_user_send_invitation="1"))
    assert len(mail.outbox) == 2
    assert mail.outbox[1].subject == "Set up your Practice Rota login"


def test_saving_without_a_button_sends_nothing(admin_client, configured, gp_user):
    assert admin_client.post(_change(gp_user), _form(gp_user)).status_code == 302
    assert mail.outbox == []


def test_a_button_smuggled_into_the_add_post_sends_once(admin_client, configured):
    admin_client.post(ADD, {"email": "new@example.com", "accounts_user_send_invitation": "1"})
    assert len(mail.outbox) == 1


def test_the_wrong_states_button_is_a_no_op(admin_client, configured, gp_user):
    admin_client.post(_change(gp_user), _form(gp_user, accounts_user_send_invitation="1"))
    assert mail.outbox == []
    invited = User.objects.create_user(email="invited@example.com")
    admin_client.post(_change(invited), _form(invited, accounts_user_send_reset_link="1"))
    assert mail.outbox == []


def test_a_rota_admin_cannot_send_to_a_superuser(admin_client, configured, staff_user):
    resp = admin_client.post(_change(staff_user),
                             _form(staff_user, accounts_user_send_reset_link="1"))
    assert resp.status_code == 403 and mail.outbox == []


def test_a_superuser_can_send_to_anyone(staff_client, configured, admin_user, staff_user):
    staff_client.post(_change(admin_user), _form(admin_user, accounts_user_send_reset_link="1"))
    staff_client.post(_change(staff_user), _form(staff_user, accounts_user_send_reset_link="1"))
    assert sorted(m.to[0] for m in mail.outbox) == ["admin@example.com", "staff@example.com"]


# --- the bulk action ---------------------------------------------------------

def test_the_bulk_action_sends_to_everyone_the_requester_may_change(
        admin_client, staff_client, configured, gp_user, staff_user):
    invited = User.objects.create_user(email="invited@example.com")
    data = {"action": "send_links",
            "_selected_action": [gp_user.pk, invited.pk, staff_user.pk]}

    resp = admin_client.post(LIST, data, follow=True)
    assert sorted(m.to[0] for m in mail.outbox) == ["gp@example.com", "invited@example.com"]
    assert mail.outbox[0].subject != mail.outbox[1].subject   # one reset, one invitation
    assert "2 sent" in resp.content.decode()

    mail.outbox.clear()
    staff_client.post(LIST, data)
    assert len(mail.outbox) == 3


def test_the_bulk_action_hands_over_links_when_it_cannot_send(admin_client, settings, gp_user):
    settings.EMAIL_HOST = ""
    resp = admin_client.post(LIST, {"action": "send_links", "_selected_action": [gp_user.pk]},
                             follow=True)
    html = resp.content.decode()
    assert "0 sent, 1 to copy" in html
    assert 'href="http://testserver/accounts/reset/' in html


# --- direct password setting is a superuser's tool now -----------------------

def test_only_a_superuser_reaches_the_direct_set_password_form(admin_client, staff_client, gp_user):
    url = f"/admin/accounts/user/{gp_user.pk}/password/"
    assert admin_client.get(url).status_code == 403
    assert admin_client.post(url, {"password1": "orchard-lantern-quiet-42",
                                   "password2": "orchard-lantern-quiet-42"}).status_code == 403
    gp_user.refresh_from_db()
    assert gp_user.check_password("pw")
    assert staff_client.get(url).status_code == 200


def test_no_change_page_links_the_direct_password_form(admin_client, staff_client, gp_user):
    """The hash field and its "this form" link are gone for everyone — an
    admin sends a link, they never set a password. A superuser's direct
    set-password view stays reachable by URL only (test above)."""
    assert "password/" not in admin_client.get(_change(gp_user)).content.decode()
    assert "password/" not in staff_client.get(_change(gp_user)).content.decode()
