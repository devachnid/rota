"""Every email leaves through accounts/mail.py. These pin the link it mints,
the headers it sets, what it returns when it cannot send, and the throttle."""

import smtplib
from datetime import timedelta

import pytest
from django.conf import settings as dj_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.mail import EmailMessage
from django.utils import timezone
from django.utils.http import urlsafe_base64_decode

from accounts.mail import (LinkToCopy, email_is_configured, link_expires,
                           send_password_link)

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def configured(settings):
    settings.EMAIL_HOST = "smtp.example"
    settings.DEFAULT_FROM_EMAIL = "Practice Rota <rota@example.org>"


def _request(rf, user=None):
    request = rf.get("/admin/accounts/user/")
    request.user = user or AnonymousUser()
    return request


def _uid_and_token(link):
    # http://testserver/accounts/reset/<uidb64>/<token>/
    parts = link.rstrip("/").split("/")
    return parts[-2], parts[-1]


def _link_in(message):
    return next(w for w in message.body.split() if w.startswith("http"))


def test_the_settings_this_module_relies_on():
    assert dj_settings.EMAIL_TIMEOUT == 10
    assert dj_settings.PASSWORD_RESET_TIMEOUT == 7 * 24 * 3600
    assert dj_settings.EMAIL_PORT == 587 and dj_settings.EMAIL_USE_TLS is True


def test_email_is_configured_means_a_host_is_named(settings):
    settings.EMAIL_HOST = ""
    assert not email_is_configured()
    settings.EMAIL_HOST = "smtp.example"
    assert email_is_configured()


def test_an_invitation_goes_to_the_person_with_a_working_link(rf, configured, admin_user):
    user = User.objects.create_user(email="new@example.com")
    assert not user.has_usable_password()

    assert send_password_link(_request(rf, admin_user), user, invite=True) is None

    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.to == ["new@example.com"]
    assert sent.subject == "Set up your Practice Rota login"
    assert sent.from_email == "Practice Rota <rota@example.org>"
    assert sent.extra_headers["X-Mailjet-TrackClick"] == "0"
    assert sent.extra_headers["X-Mailjet-TrackOpen"] == "0"
    link = _link_in(sent)
    assert link.startswith("http://testserver/accounts/reset/")
    uidb64, token = _uid_and_token(link)
    assert urlsafe_base64_decode(uidb64).decode() == str(user.pk)
    assert default_token_generator.check_token(user, token)
    assert "ask admin@example.com" in sent.body      # who sent it is who to ask
    assert "&#" not in sent.body                      # plain text, not HTML-escaped
    user.refresh_from_db()
    assert user.password_link_sent_at is not None


def test_a_reset_reads_as_a_reset(rf, configured, gp_user):
    send_password_link(_request(rf), gp_user, invite=False)
    sent = mail.outbox[0]
    assert sent.subject == "Reset your Practice Rota password"
    assert "ask a rota admin" in sent.body            # anonymous request: no named contact
    assert "ignore this" in sent.body


def test_the_body_names_the_expiry_date(rf, configured, gp_user):
    send_password_link(_request(rf), gp_user, invite=False)
    expires = timezone.localtime(link_expires(timezone.now()))
    assert f"{expires:%-d %B}" in mail.outbox[0].body


def test_without_a_relay_the_link_comes_back_to_copy(rf, settings, admin_user, gp_user):
    settings.EMAIL_HOST = ""
    result = send_password_link(_request(rf, admin_user), gp_user, invite=False)
    assert isinstance(result, LinkToCopy) and result.reason == ""
    assert mail.outbox == []
    _, token = _uid_and_token(result.link)
    assert default_token_generator.check_token(gp_user, token)
    gp_user.refresh_from_db()
    assert gp_user.password_link_sent_at is not None


def test_a_refusing_relay_returns_the_link_and_the_reason(rf, configured, monkeypatch,
                                                          admin_user, gp_user):
    def refuse(self, fail_silently=False):
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
    monkeypatch.setattr(EmailMessage, "send", refuse)
    result = send_password_link(_request(rf, admin_user), gp_user, invite=False)
    assert isinstance(result, LinkToCopy)
    assert "535" in result.reason and "bad credentials" in result.reason
    _, token = _uid_and_token(result.link)
    assert default_token_generator.check_token(gp_user, token)


def test_a_connection_failure_is_a_reason_too(rf, configured, monkeypatch, admin_user, gp_user):
    def refuse(self, fail_silently=False):
        raise ConnectionRefusedError(111, "Connection refused")
    monkeypatch.setattr(EmailMessage, "send", refuse)
    result = send_password_link(_request(rf, admin_user), gp_user, invite=False)
    assert isinstance(result, LinkToCopy) and "Connection refused" in result.reason


def test_the_throttle_only_applies_when_asked(rf, configured, gp_user):
    gp_user.password_link_sent_at = timezone.now() - timedelta(minutes=1)
    gp_user.save()
    assert send_password_link(_request(rf), gp_user, invite=False, throttle=True) is None
    assert mail.outbox == []                       # quiet: nothing sent, nothing returned
    assert send_password_link(_request(rf), gp_user, invite=False) is None
    assert len(mail.outbox) == 1                   # an admin's send is never throttled


def test_the_throttle_lifts_after_five_minutes(rf, configured, gp_user):
    gp_user.password_link_sent_at = timezone.now() - timedelta(minutes=6)
    gp_user.save()
    assert send_password_link(_request(rf), gp_user, invite=False, throttle=True) is None
    assert len(mail.outbox) == 1


def test_link_expiry_follows_the_setting(settings):
    settings.PASSWORD_RESET_TIMEOUT = 3600
    now = timezone.now()
    assert link_expires(now) == now + timedelta(hours=1)
