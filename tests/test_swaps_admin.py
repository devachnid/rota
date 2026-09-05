"""Swap requests in the admin: a read-only record, the Checks field, and
Approve / Decline buttons that run the same service as the Requests page.
The status used to be an editable dropdown; setting it to Applied by hand
relabelled the row and left the rota alone."""

from datetime import timedelta

import pytest

from rota.models import RotaEntry, SwapRequest
from tests.factories import MON, make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db

LIST = "/admin/rota/swaprequest/"
APPROVE = {"rota_swaprequest_approve_swap": "1"}
DECLINE = {"rota_swaprequest_decline_swap": "1"}
FRI = MON + timedelta(days=4)


def _change(req):
    return f"{LIST}{req.pk}/change/"


@pytest.fixture
def accepted():
    """Alice's Fri PM for Beth's Mon AM, the cover-for-each-other kind,
    accepted by Beth and awaiting an admin."""
    research, routine = make_session_type("Research"), make_session_type("Routine")
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    make_entry(a, day=FRI, part="PM", session_type=research)
    make_entry(b, day=MON, part="AM", session_type=routine)
    return SwapRequest.objects.create(
        proposer=a, proposer_day=FRI, proposer_part="PM",
        colleague=b, colleague_day=MON, colleague_part="AM",
        status=SwapRequest.Status.ACCEPTED)


def test_the_record_is_read_only_and_there_is_no_add_page(admin_client, accepted):
    html = admin_client.get(_change(accepted)).content.decode()
    assert 'name="status"' not in html
    assert 'name="admin_comment"' in html
    assert "Ready to apply." in html
    assert "Beth Brown takes Alice Adams" in html
    assert admin_client.get(LIST + "add/").status_code == 403


def test_the_checks_field_lists_the_problems(admin_client, accepted):
    RotaEntry.objects.filter(clinician=accepted.colleague).delete()
    html = admin_client.get(_change(accepted)).content.decode()
    assert "<li>Beth Brown has no session on Mon 20 Jul AM.</li>" in html
    assert "Ready to apply." not in html


def test_the_buttons_follow_the_status(admin_client, accepted):
    approve, decline = 'name="rota_swaprequest_approve_swap"', 'name="rota_swaprequest_decline_swap"'
    html = admin_client.get(_change(accepted)).content.decode()
    assert approve in html and decline in html
    accepted.status = SwapRequest.Status.PROPOSED
    accepted.save()
    html = admin_client.get(_change(accepted)).content.decode()
    assert approve not in html and decline in html
    accepted.status = SwapRequest.Status.DECLINED
    accepted.save()
    html = admin_client.get(_change(accepted)).content.decode()
    assert approve not in html and decline not in html
    assert "Declined." in html


def test_approve_applies_the_swap(admin_client, admin_user, accepted):
    resp = admin_client.post(_change(accepted), {"admin_comment": "", **APPROVE}, follow=True)
    accepted.refresh_from_db()
    assert accepted.status == SwapRequest.Status.APPROVED
    assert accepted.decided_by == admin_user and accepted.decided_at is not None
    assert RotaEntry.objects.get(day=FRI, part="PM").clinician == accepted.colleague
    assert RotaEntry.objects.get(day=MON, part="AM").clinician == accepted.proposer
    assert "Swap applied." in resp.content.decode()


def test_approve_reports_the_problems_instead_of_applying(admin_client, accepted):
    RotaEntry.objects.filter(clinician=accepted.colleague).delete()
    resp = admin_client.post(_change(accepted), {"admin_comment": "", **APPROVE}, follow=True)
    accepted.refresh_from_db()
    assert accepted.status == SwapRequest.Status.ACCEPTED
    assert "Not applied: Beth Brown has no session on Mon 20 Jul AM." in resp.content.decode()


def test_decline_keeps_the_comment_and_stamps_the_decision(admin_client, admin_user, accepted):
    admin_client.post(_change(accepted), {"admin_comment": "Duty cover is short that Friday.",
                                          **DECLINE})
    accepted.refresh_from_db()
    assert accepted.status == SwapRequest.Status.DECLINED
    assert accepted.admin_comment == "Duty cover is short that Friday."
    assert accepted.decided_by == admin_user and accepted.decided_at is not None
    assert RotaEntry.objects.get(day=FRI, part="PM").clinician == accepted.proposer


def test_the_status_cannot_be_set_by_hand(admin_client, accepted):
    admin_client.post(_change(accepted), {"admin_comment": "", "status": "APPROVED",
                                          "decided_by": "1"})
    accepted.refresh_from_db()
    assert accepted.status == SwapRequest.Status.ACCEPTED and accepted.decided_by is None
    assert RotaEntry.objects.get(day=FRI, part="PM").clinician == accepted.proposer


def test_a_smuggled_approve_on_an_open_proposal_does_nothing(admin_client, accepted):
    accepted.status = SwapRequest.Status.PROPOSED
    accepted.save()
    admin_client.post(_change(accepted), {"admin_comment": "", **APPROVE})
    accepted.refresh_from_db()
    assert accepted.status == SwapRequest.Status.PROPOSED
    assert RotaEntry.objects.get(day=FRI, part="PM").clinician == accepted.proposer


def test_the_list_shows_the_exchange(admin_client, accepted):
    html = admin_client.get(LIST).content.decode()
    assert "Fri 24 Jul PM ↔ Mon 20 Jul AM" in html
