"""The form every signed-in page can open, and what a send records."""

from datetime import timedelta

import pytest
from django.core import mail
from django.core.mail import EmailMessage
from django.utils import timezone

from feedback.models import Feedback
from feedback.views import HOURLY_LIMIT, TOO_MANY

pytestmark = pytest.mark.django_db

FORM = "/feedback/form/"
SEND = "/feedback/send/"


def test_anonymous_visitors_are_sent_to_log_in(client):
    resp = client.get(FORM)
    assert resp.status_code == 302 and resp["Location"].startswith("/accounts/login/")
    assert client.post(SEND, {"kind": "BUG", "message": "x"}).status_code == 302
    assert Feedback.objects.count() == 0


def test_the_form_offers_both_kinds_with_bug_preselected(gp_client):
    html = gp_client.get(FORM).content.decode()
    assert 'type="radio" name="kind" value="BUG" checked' in html
    assert 'type="radio" name="kind" value="IDEA">' in html
    assert 'hx-post="/feedback/send/"' in html and 'hx-target="#modal"' in html
    assert "{%" not in html and "{{" not in html


def test_a_send_records_what_the_reporter_said_and_where_they_were(gp_client, gp_user):
    resp = gp_client.post(
        SEND, {"kind": "IDEA", "message": "  A print view  ", "viewport": "390x844"},
        HTTP_HX_CURRENT_URL="http://testserver/rota/?week=2026-09-07",
        HTTP_USER_AGENT="Mozilla/5.0 (Android)")
    assert resp.status_code == 200
    fb = Feedback.objects.get()
    assert (fb.kind, fb.message, fb.viewport) == ("IDEA", "A print view", "390x844")
    assert fb.page == "/rota/?week=2026-09-07"
    assert fb.user_agent == "Mozilla/5.0 (Android)"
    assert fb.reporter == gp_user and fb.status == Feedback.Status.NEW
    html = resp.content.decode()
    assert "Thanks" in html and "Your idea is in." in html and "gp@example.com" in html


def test_a_foreign_or_missing_page_is_stored_blank(gp_client):
    gp_client.post(SEND, {"kind": "BUG", "message": "one"},
                   HTTP_HX_CURRENT_URL="https://evil.example/rota/")
    gp_client.post(SEND, {"kind": "BUG", "message": "two"})
    assert [fb.page for fb in Feedback.objects.order_by("message")] == ["", ""]


def test_long_headers_are_capped_and_a_bad_viewport_is_dropped(gp_client):
    gp_client.post(SEND, {"kind": "BUG", "message": "x", "viewport": "not-a-size"},
                   HTTP_HX_CURRENT_URL="http://testserver/rota/?q=" + "a" * 500,
                   HTTP_USER_AGENT="U" * 500)
    fb = Feedback.objects.get()
    assert len(fb.page) == 300 and len(fb.user_agent) == 300 and fb.viewport == ""


def test_an_empty_message_re_renders_the_form_with_the_error(gp_client):
    resp = gp_client.post(SEND, {"kind": "IDEA", "message": "   "})
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Say a little about it first." in html
    assert 'value="IDEA" checked' in html  # the choice survives the round trip
    assert Feedback.objects.count() == 0


def test_the_eleventh_report_in_an_hour_is_refused(gp_client, gp_user):
    for i in range(HOURLY_LIMIT):
        Feedback.objects.create(kind="BUG", message=f"r{i}", reporter=gp_user)
    resp = gp_client.post(SEND, {"kind": "BUG", "message": "one more"})
    assert resp.status_code == 200 and TOO_MANY in resp.content.decode()
    assert Feedback.objects.count() == HOURLY_LIMIT


def test_reports_older_than_an_hour_do_not_count(gp_client, gp_user):
    for i in range(HOURLY_LIMIT):
        Feedback.objects.create(kind="BUG", message=f"r{i}", reporter=gp_user)
    Feedback.objects.update(created_at=timezone.now() - timedelta(hours=2))
    gp_client.post(SEND, {"kind": "BUG", "message": "fresh"})
    assert Feedback.objects.count() == HOURLY_LIMIT + 1


def test_another_reporters_reports_do_not_count(gp_client, gp_user, admin_user):
    for i in range(HOURLY_LIMIT):
        Feedback.objects.create(kind="BUG", message=f"r{i}", reporter=admin_user)
    gp_client.post(SEND, {"kind": "BUG", "message": "mine"})
    assert Feedback.objects.filter(reporter=gp_user).count() == 1


def test_a_send_tells_the_maintainers(configured, gp_client, staff_user):
    gp_client.post(SEND, {"kind": "BUG", "message": "The grid is blank"})
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["staff@example.com"]
    assert "The grid is blank" in mail.outbox[0].body


def test_a_relay_failure_never_reaches_the_reporter(configured, gp_client, staff_user, monkeypatch):
    def boom(self, fail_silently=False):
        raise ConnectionError("relay down")
    monkeypatch.setattr(EmailMessage, "send", boom)
    resp = gp_client.post(SEND, {"kind": "BUG", "message": "x"})
    assert resp.status_code == 200 and "Thanks" in resp.content.decode()
    assert Feedback.objects.count() == 1
