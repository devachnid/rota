"""Triage in the admin: the list, the reply button, the bulk actions, the
sidebar item and the dashboard line."""

import pytest
from django.core import mail

from feedback.models import Feedback

pytestmark = pytest.mark.django_db

LIST = "/admin/feedback/feedback/"
SEND_REPLY = {"feedback_feedback_send_reply": "1"}


def _change(fb):
    return f"{LIST}{fb.pk}/change/"


def _form(fb, **extra):
    """A change-form POST that leaves the record as it is unless told."""
    data = {"status": fb.status, "admin_note": fb.admin_note, "reply": fb.reply}
    data.update(extra)
    return data


@pytest.fixture
def report(gp_user):
    return Feedback.objects.create(kind="BUG", message="The grid is blank on Mondays",
                                   page="/rota/", reporter=gp_user)


def test_the_list_and_change_form_render_and_there_is_no_add_page(admin_client, report):
    html = admin_client.get(LIST).content.decode()
    assert "The grid is blank on Mondays" in html and "gp@example.com" in html
    change = admin_client.get(_change(report))
    assert change.status_code == 200
    # The submit-line button unfold renders for the action, by its POST name.
    assert 'name="feedback_feedback_send_reply"' in change.content.decode()
    assert admin_client.get(LIST + "add/").status_code == 403


def test_the_summary_is_one_line_of_at_most_sixty_characters(admin_client, gp_user):
    Feedback.objects.create(kind="IDEA", message="a" * 100, reporter=gp_user)
    Feedback.objects.create(kind="IDEA", message="first line\nsecond line", reporter=gp_user)
    html = admin_client.get(LIST).content.decode()
    assert "a" * 59 + "…" in html and "a" * 60 not in html
    assert "first line second line" in html


def test_send_reply_emails_the_reporter_and_stamps_the_record(configured, admin_client, admin_user, report):
    resp = admin_client.post(_change(report), _form(report, reply="Fixed tonight.", status="DONE", **SEND_REPLY),
                             follow=True)
    assert "Reply sent to gp@example.com." in resp.content.decode()
    report.refresh_from_db()
    assert report.reply == "Fixed tonight." and report.status == "DONE"
    assert report.replied_at is not None and report.replied_by == admin_user
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["gp@example.com"] and mail.outbox[0].reply_to == ["admin@example.com"]


def test_sending_does_not_touch_the_status(configured, admin_client, report):
    admin_client.post(_change(report), _form(report, reply="Looking into it.", status="SEEN", **SEND_REPLY))
    report.refresh_from_db()
    assert report.status == "SEEN" and report.replied_at is not None


def test_saving_without_the_button_sends_nothing(configured, admin_client, report):
    admin_client.post(_change(report), _form(report, reply="Draft", status="SEEN"))
    report.refresh_from_db()
    assert report.reply == "Draft" and report.replied_at is None and mail.outbox == []


def test_a_blank_reply_is_refused(configured, admin_client, report):
    resp = admin_client.post(_change(report), _form(report, reply="  ", **SEND_REPLY), follow=True)
    assert "Write the reply first." in resp.content.decode()
    report.refresh_from_db()
    assert report.replied_at is None and mail.outbox == []


def test_without_a_relay_the_reply_is_saved_but_not_sent(admin_client, report, settings):
    settings.EMAIL_HOST = ""
    resp = admin_client.post(_change(report), _form(report, reply="Hello", **SEND_REPLY), follow=True)
    assert "Reply saved but not sent: Email isn&#x27;t set up." in resp.content.decode() \
        or "Reply saved but not sent: Email isn't set up." in resp.content.decode()
    report.refresh_from_db()
    assert report.reply == "Hello" and report.replied_at is None and mail.outbox == []


def test_a_vanished_reporter_has_no_button_and_a_smuggled_one_sends_nothing(configured, admin_client, report, gp_user):
    gp_user.delete()
    report.refresh_from_db()
    # The phrase "Send reply" is also in the help text; the button is what must go.
    assert 'name="feedback_feedback_send_reply"' not in admin_client.get(_change(report)).content.decode()
    admin_client.post(_change(report), _form(report, reply="Hello", **SEND_REPLY))
    report.refresh_from_db()
    assert report.replied_at is None and mail.outbox == []


def test_bulk_mark_seen_and_done(admin_client, gp_user):
    a = Feedback.objects.create(kind="BUG", message="a", reporter=gp_user)
    b = Feedback.objects.create(kind="BUG", message="b", reporter=gp_user)
    admin_client.post(LIST, {"action": "mark_seen", "_selected_action": [a.pk, b.pk]})
    assert set(Feedback.objects.values_list("status", flat=True)) == {"SEEN"}
    admin_client.post(LIST, {"action": "mark_done", "_selected_action": [a.pk]})
    assert Feedback.objects.get(pk=a.pk).status == "DONE"
    assert Feedback.objects.get(pk=b.pk).status == "SEEN"


def test_feedback_is_the_last_item_of_records_in_the_sidebar(admin_client, admin_user, rf):
    from rota.admin_site import navigation
    from rota.models import PracticeSettings
    PracticeSettings.load()
    request = rf.get("/admin/")
    request.user = admin_user
    records = next(g for g in navigation(request) if g["title"] == "Records")
    assert records["items"][-1]["title"] == "Feedback"
    assert 'href="/admin/feedback/feedback/"' in admin_client.get("/admin/").content.decode()


def test_the_dashboard_counts_unread_feedback_and_links_to_exactly_those_rows(admin_client, gp_user):
    from rota.admin_dashboard import health
    from rota.models import PracticeSettings
    PracticeSettings.load()
    Feedback.objects.create(kind="BUG", message="unread-one", reporter=gp_user)
    Feedback.objects.create(kind="BUG", message="already-seen", reporter=gp_user, status="SEEN")
    line = {h["label"]: h for h in health()}["Feedback not yet looked at"]
    assert line["count"] == 1 and line["url"].endswith("?status__exact=NEW")
    resp = admin_client.get(line["url"])
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "unread-one" in html and "already-seen" not in html
