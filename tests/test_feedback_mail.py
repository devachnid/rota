"""Two emails: the notification to the people who maintain the app, and the
reply an admin sends the reporter. Both leave through the same door as the
password links, and neither may lose a report or raise into a page."""

import logging

import pytest
from django.core import mail
from django.core.mail import EmailMessage

from accounts.models import User
from feedback.mail import notify_admins, send_reply
from feedback.models import Feedback

pytestmark = pytest.mark.django_db


def _request(rf, user):
    request = rf.get("/rota/", HTTP_HOST="testserver")
    request.user = user
    return request


@pytest.fixture
def report(gp_user):
    return Feedback.objects.create(
        kind="BUG", message="Two lines\nof detail", page="/rota/?week=2026-09-07",
        viewport="390x844", user_agent="UA", reporter=gp_user)


def _boom(monkeypatch):
    def send(self, fail_silently=False):
        raise ConnectionError("relay down")
    monkeypatch.setattr(EmailMessage, "send", send)


def test_notification_goes_to_active_superusers_only(configured, rf, report, gp_user, admin_user):
    User.objects.create_superuser(email="dev@example.com", password="pw")
    User.objects.create_superuser(email="second@example.com", password="pw")
    gone = User.objects.create_superuser(email="gone@example.com", password="pw")
    gone.is_active = False
    gone.save()
    assert notify_admins(_request(rf, gp_user), report) is True
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    # The rota admin (admin_user) runs the practice, not the code: not told.
    assert sorted(msg.to) == ["dev@example.com", "second@example.com"]
    assert msg.subject == "[Rota] Bug report from gp@example.com"
    assert msg.extra_headers["X-Mailjet-TrackClick"] == "0"
    assert msg.extra_headers["X-Mailjet-TrackOpen"] == "0"
    assert "Two lines\nof detail" in msg.body
    assert "/rota/?week=2026-09-07" in msg.body and "390x844" in msg.body and "UA" in msg.body
    assert f"http://testserver/admin/feedback/feedback/{report.pk}/change/" in msg.body


def test_an_idea_is_labelled_as_one(configured, rf, gp_user, staff_user):
    idea = Feedback.objects.create(kind="IDEA", message="Print view", reporter=gp_user)
    assert notify_admins(_request(rf, gp_user), idea) is True
    assert mail.outbox[0].subject == "[Rota] Idea from gp@example.com"


def test_no_relay_means_no_send_and_no_error(rf, report, gp_user, staff_user, settings):
    settings.EMAIL_HOST = ""
    assert notify_admins(_request(rf, gp_user), report) is False
    assert mail.outbox == []


def test_no_superuser_with_an_email_means_no_send(configured, rf, report, gp_user, admin_user):
    assert notify_admins(_request(rf, gp_user), report) is False
    assert mail.outbox == []


def test_a_relay_failure_is_logged_not_raised(configured, rf, report, gp_user, staff_user, monkeypatch, caplog):
    _boom(monkeypatch)
    with caplog.at_level(logging.ERROR, logger="feedback.mail"):
        assert notify_admins(_request(rf, gp_user), report) is False
    assert "could not be sent" in caplog.text


def test_reply_reaches_the_reporter_with_the_admin_as_reply_to(configured, rf, report, admin_user):
    report.reply = "Fixed in tonight's update — thank you."
    assert send_reply(_request(rf, admin_user), report) is None
    msg = mail.outbox[0]
    assert msg.to == ["gp@example.com"]
    assert msg.reply_to == ["admin@example.com"]
    assert msg.subject == "Reply to your rota bug report"
    assert "Fixed in tonight's update — thank you." in msg.body
    assert "> Two lines\n> of detail" in msg.body
    assert "/rota/?week=2026-09-07" in msg.body
    assert "admin@example.com" in msg.body
    assert msg.extra_headers["X-Mailjet-TrackClick"] == "0"


def test_reply_to_an_idea_is_labelled_as_one(configured, rf, gp_user, admin_user):
    idea = Feedback.objects.create(kind="IDEA", message="Print view", reporter=gp_user, reply="Good idea.")
    assert send_reply(_request(rf, admin_user), idea) is None
    assert mail.outbox[0].subject == "Reply to your rota idea"


def test_reply_without_a_relay_says_so_and_sends_nothing(rf, report, admin_user, settings):
    settings.EMAIL_HOST = ""
    report.reply = "Hello"
    assert send_reply(_request(rf, admin_user), report) == "Email isn't set up"
    assert mail.outbox == []


def test_reply_to_a_vanished_reporter_is_refused(configured, rf, report, admin_user, gp_user):
    gp_user.delete()
    report.refresh_from_db()
    report.reply = "Hello"
    assert send_reply(_request(rf, admin_user), report) == "The reporter's account is gone"
    assert mail.outbox == []


def test_reply_relay_failure_returns_the_reason_and_logs(configured, rf, report, admin_user, monkeypatch, caplog):
    _boom(monkeypatch)
    report.reply = "Hello"
    with caplog.at_level(logging.ERROR, logger="feedback.mail"):
        assert send_reply(_request(rf, admin_user), report) == "relay down"
    assert "could not be sent" in caplog.text
