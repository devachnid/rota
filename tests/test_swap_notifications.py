"""Swaps tell people: the colleague when asked, the proposer when answered,
every rota admin when a swap awaits approval, and both GPs when an admin
decides — plus the nav counts and the dashboard line that point at the same
things. Before this, the only trace of a swap was a card on My schedule,
which the login landing page does not point at."""

from datetime import date, timedelta

import pytest
from django.core import mail
from django.core.mail import EmailMessage

from accounts.models import User
from rota import mail as swap_mail
from rota.admin_dashboard import health
from rota.models import RotaEntry, SwapRequest
from tests.factories import make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db

APPROVE = {"rota_swaprequest_approve_swap": "1"}


def _gp(name, email):
    c = make_clinician(name)
    c.user = User.objects.create_user(email=email, password="pw")
    c.save()
    return c


def _request(rf, user):
    request = rf.get("/rota/", HTTP_HOST="testserver")
    request.user = user
    return request


@pytest.fixture
def pair(configured):
    """Alice and Beth both sign in; Alice works a session in eleven days,
    Beth one in seven, neither the other's — the cover-for-each-other kind,
    proposed by Alice with a message."""
    routine = make_session_type("Routine")
    a, b = _gp("Alice Adams", "alice@example.com"), _gp("Beth Brown", "beth@example.com")
    theirs, mine = date.today() + timedelta(days=7), date.today() + timedelta(days=11)
    make_entry(a, day=mine, part="PM", session_type=routine)
    make_entry(b, day=theirs, part="AM", session_type=routine)
    req = SwapRequest.objects.create(
        proposer=a, proposer_day=mine, proposer_part="PM",
        colleague=b, colleague_day=theirs, colleague_part="AM",
        message="School run that afternoon")
    return a, b, req


# --------------------------------------------------------------------------
# the messages
# --------------------------------------------------------------------------

def test_proposed_goes_to_the_colleague_with_reply_to_the_proposer(rf, pair):
    a, b, req = pair
    assert swap_mail.swap_proposed(_request(rf, a.user), req) is True
    [msg] = mail.outbox
    assert msg.to == ["beth@example.com"] and msg.reply_to == ["alice@example.com"]
    assert msg.subject == "[Rota] Alice Adams would like to swap a session with you"
    assert "Beth Brown takes Alice Adams's" in msg.body
    assert "Alice Adams said:\n> School run that afternoon" in msg.body
    assert "Accept or decline on My schedule: http://testserver/me/" in msg.body
    assert msg.extra_headers["X-Mailjet-TrackClick"] == "0"
    assert msg.extra_headers["X-Mailjet-TrackOpen"] == "0"


def test_accepted_goes_to_the_proposer_and_to_every_active_rota_admin(rf, pair, admin_user):
    a, b, req = pair
    User.objects.create_user(email="second@example.com", password="pw", is_rota_admin=True)
    gone = User.objects.create_user(email="gone@example.com", password="pw", is_rota_admin=True)
    gone.is_active = False
    gone.save()
    User.objects.create_user(email="plain@example.com", password="pw")  # a GP: not told
    req.status = SwapRequest.Status.ACCEPTED
    req.save()
    assert swap_mail.swap_accepted(_request(rf, b.user), req) == 2
    by_subject = {m.subject: m for m in mail.outbox}
    to_alice = by_subject["[Rota] Beth Brown accepted your swap — awaiting admin approval"]
    assert to_alice.to == ["alice@example.com"] and to_alice.reply_to == ["beth@example.com"]
    assert "you will get an email when they decide" in to_alice.body
    to_admins = by_subject["[Rota] Swap awaiting your approval: Alice Adams and Beth Brown"]
    assert sorted(to_admins.to) == ["admin@example.com", "second@example.com"]
    assert "Approve or decline: http://testserver/requests/" in to_admins.body
    assert "> School run that afternoon" in to_admins.body
    assert "cannot be applied" not in to_admins.body


def test_the_admins_hear_about_problems_when_the_rota_has_moved(rf, pair, admin_user):
    a, b, req = pair
    RotaEntry.objects.filter(clinician=b).delete()
    swap_mail.swap_accepted(_request(rf, b.user), req)
    [to_admins] = [m for m in mail.outbox if "awaiting your approval" in m.subject]
    assert "As the rota stands it cannot be applied:\n- Beth Brown has no session on" in to_admins.body


def test_declined_by_the_colleague_carries_their_comment(rf, pair):
    a, b, req = pair
    req.colleague_comment = "Away that week, sorry"
    req.status = SwapRequest.Status.DECLINED
    req.save()
    assert swap_mail.swap_declined_by_colleague(_request(rf, b.user), req) is True
    [msg] = mail.outbox
    assert msg.to == ["alice@example.com"] and msg.reply_to == ["beth@example.com"]
    assert msg.subject == "[Rota] Beth Brown declined your swap"
    assert "Beth Brown said:\n> Away that week, sorry" in msg.body


def test_decided_goes_to_both_gps_with_the_admins_words(rf, pair, admin_user):
    a, b, req = pair
    req.status = SwapRequest.Status.DECLINED
    req.admin_comment = "Duty cover is short that day."
    req.save()
    assert swap_mail.swap_decided(_request(rf, admin_user), req) is True
    [msg] = mail.outbox
    assert sorted(msg.to) == ["alice@example.com", "beth@example.com"]
    assert msg.reply_to == ["admin@example.com"]
    assert msg.subject == "[Rota] Swap declined: Alice Adams and Beth Brown"
    assert "was declined by admin@example.com" in msg.body
    assert "admin@example.com said:\n> Duty cover is short that day." in msg.body

    mail.outbox.clear()
    req.status = SwapRequest.Status.APPROVED
    req.save()
    swap_mail.swap_decided(_request(rf, admin_user), req, what="Captured before applying.")
    [msg] = mail.outbox
    assert msg.subject == "[Rota] Swap applied: Alice Adams and Beth Brown"
    assert "applied to the rota by admin@example.com" in msg.body
    assert "Captured before applying." in msg.body


def test_nothing_is_sent_without_a_relay(rf, pair, settings):
    a, b, req = pair
    settings.EMAIL_HOST = ""
    assert swap_mail.swap_proposed(_request(rf, a.user), req) is False
    assert mail.outbox == []


def test_a_colleague_with_no_login_is_skipped_and_nothing_raises(rf, pair):
    a, b, req = pair
    b.user = None
    b.save()
    req.refresh_from_db()
    assert swap_mail.swap_proposed(_request(rf, a.user), req) is False
    assert mail.outbox == []


def test_a_relay_failure_is_logged_not_raised(rf, pair, monkeypatch, caplog):
    a, b, req = pair

    def send(self, fail_silently=False):
        raise ConnectionError("relay down")
    monkeypatch.setattr(EmailMessage, "send", send)
    with caplog.at_level("ERROR", logger="rota.mail"):
        assert swap_mail.swap_proposed(_request(rf, a.user), req) is False
    assert "swap email swap_proposed for #%d could not be sent" % req.pk in caplog.text


def test_a_failure_before_the_send_is_logged_not_raised(rf, pair, monkeypatch, caplog):
    """A rendering error is as much the journal's as a relay error: nothing
    between deciding to send and sending may reach a page."""
    a, b, req = pair

    def render(*args, **kwargs):
        raise RuntimeError("template broke")
    monkeypatch.setattr(swap_mail, "render_to_string", render)
    with caplog.at_level("ERROR", logger="rota.mail"):
        assert swap_mail.swap_proposed(_request(rf, a.user), req) is False
    assert "could not be sent" in caplog.text and mail.outbox == []


def test_an_email_failure_never_touches_the_decision(admin_client, pair, monkeypatch):
    """The admin's Approve applies the swap inside Django's change-form
    transaction; an exception from the email would roll it back and 500.
    The mail layer swallows its own failures, and the action reports the
    decision it made."""
    a, b, req = pair
    req.status = SwapRequest.Status.ACCEPTED
    req.save()

    def render(*args, **kwargs):
        raise RuntimeError("template broke")
    monkeypatch.setattr(swap_mail, "render_to_string", render)
    resp = admin_client.post(f"/admin/rota/swaprequest/{req.pk}/change/",
                             {"admin_comment": "", **APPROVE}, follow=True)
    req.refresh_from_db()
    assert req.status == SwapRequest.Status.APPROVED
    assert RotaEntry.objects.get(clinician=b, day=req.proposer_day).part == "PM"
    assert "Swap applied." in resp.content.decode()
    assert mail.outbox == []


# --------------------------------------------------------------------------
# the pages send them
# --------------------------------------------------------------------------

def test_proposing_from_the_form_emails_the_colleague(client, pair):
    a, b, req = pair
    mine, theirs = RotaEntry.objects.get(clinician=a), RotaEntry.objects.get(clinician=b)
    req.delete()
    client.force_login(a.user)
    resp = client.post("/me/swap/new/", {"my_entry_id": mine.id, "their_entry_id": theirs.id,
                                          "message": "Please?"})
    assert resp.status_code == 302
    [msg] = mail.outbox
    assert msg.to == ["beth@example.com"] and "> Please?" in msg.body


def test_accepting_emails_the_proposer_and_the_admins(client, pair, admin_user):
    a, b, req = pair
    client.force_login(b.user)
    client.post(f"/me/swap/{req.pk}/accept/")
    assert sorted(m.to[0] for m in mail.outbox) == ["admin@example.com", "alice@example.com"]


def test_declining_with_a_comment_emails_the_proposer_and_shows_them_the_comment(client, pair):
    a, b, req = pair
    client.force_login(b.user)
    client.post(f"/me/swap/{req.pk}/decline/", {"comment": "Too short notice"})
    req.refresh_from_db()
    assert req.status == SwapRequest.Status.DECLINED
    assert req.colleague_comment == "Too short notice"
    [msg] = mail.outbox
    assert msg.to == ["alice@example.com"] and "> Too short notice" in msg.body
    client.force_login(a.user)
    html = client.get("/me/").content.decode()
    assert "Beth Brown: “Too short notice”" in html


def test_the_decline_form_on_my_schedule_has_a_comment_box(client, pair):
    a, b, req = pair
    client.force_login(b.user)
    html = client.get("/me/").content.decode()
    assert f'action="/me/swap/{req.pk}/decline/"' in html
    assert 'name="comment"' in html


def test_approving_from_requests_emails_both_with_what_happened(admin_client, pair):
    a, b, req = pair
    req.status = SwapRequest.Status.ACCEPTED
    req.save()
    admin_client.post(f"/requests/swap/{req.pk}/approve/")
    req.refresh_from_db()
    assert req.status == SwapRequest.Status.APPROVED
    [msg] = mail.outbox
    assert sorted(msg.to) == ["alice@example.com", "beth@example.com"]
    # The sentence is captured before the entries move; afterwards the rota
    # no longer reads as this swap.
    assert "Beth Brown takes Alice Adams's" in msg.body


def test_approving_from_the_admin_emails_both_too(admin_client, pair):
    a, b, req = pair
    req.status = SwapRequest.Status.ACCEPTED
    req.save()
    admin_client.post(f"/admin/rota/swaprequest/{req.pk}/change/", {"admin_comment": "", **APPROVE})
    req.refresh_from_db()
    assert req.status == SwapRequest.Status.APPROVED
    [msg] = mail.outbox
    assert sorted(msg.to) == ["alice@example.com", "beth@example.com"]
    assert msg.subject == "[Rota] Swap applied: Alice Adams and Beth Brown"


def test_declining_from_requests_emails_both_with_the_comment(admin_client, pair):
    a, b, req = pair
    admin_client.post(f"/requests/swap/{req.pk}/decline/", {"comment": "Not this week"})
    [msg] = mail.outbox
    assert sorted(msg.to) == ["alice@example.com", "beth@example.com"]
    assert "> Not this week" in msg.body


# --------------------------------------------------------------------------
# the nav and the dashboard point at the same things
# --------------------------------------------------------------------------

def test_the_nav_counts_what_is_waiting_for_each_person(client, admin_client, pair):
    a, b, req = pair
    client.force_login(b.user)
    html = client.get("/rota/").content.decode()
    assert '<span class="nav-count" title="1 swap waiting for you">1</span>' in html
    client.force_login(a.user)
    assert "nav-count" not in client.get("/rota/").content.decode()
    # Nothing awaits the admin until the colleague has accepted.
    assert "nav-count" not in admin_client.get("/rota/").content.decode()
    req.status = SwapRequest.Status.ACCEPTED
    req.save()
    html = admin_client.get("/rota/").content.decode()
    assert '<span class="nav-count" title="1 swap awaiting your approval">1</span>' in html
    assert html.count("nav-count") == 3  # nav Requests, tab bar More, sheet Requests
    client.logout()
    assert client.get("/accounts/login/").status_code == 200


def test_the_dashboard_counts_swaps_awaiting_approval(admin_client, pair):
    a, b, req = pair
    lines = {h["label"]: h for h in health()}
    assert lines["Swaps awaiting your approval"]["count"] == 0
    req.status = SwapRequest.Status.ACCEPTED
    req.save()
    lines = {h["label"]: h for h in health()}
    assert lines["Swaps awaiting your approval"]["count"] == 1
    assert lines["Swaps awaiting your approval"]["url"] == "/requests/"
    assert "Swaps awaiting your approval" in admin_client.get("/admin/").content.decode()


def test_the_nav_count_is_styled_to_be_acted_on():
    from pathlib import Path
    css = (Path(__file__).resolve().parents[1] / "static/css/components.css").read_text()
    block = css[css.index(".nav-count {"):]
    block = block[:block.index("}")]
    assert "background: var(--danger)" in block and "color: var(--surface)" in block
