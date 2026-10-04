"""Review item 7A — the phone's tab bar leads with Me — and the swap
card's reason box, which was a bare browser input between two buttons."""

import pytest

from rota.models import PracticeSettings, SwapRequest
from tests.factories import MON, make_clinician
from tests.test_css_cascade import rule

pytestmark = pytest.mark.django_db


def _tabbar(html):
    return html[html.index('<nav class="tabbar"'):html.index("</nav>", html.index('<nav class="tabbar"'))]


def test_the_phone_leads_with_my_schedule(gp_client):
    """On a phone My Schedule is the screen; the week is a forty-column table."""
    PracticeSettings.load()
    bar = _tabbar(gp_client.get("/me/").content.decode())
    order = [bar.index(f">{label}") for label in ("Me", "Day", "Week", "More")]
    assert order == sorted(order)


def _swap(proposer, colleague):
    return SwapRequest.objects.create(
        proposer=proposer, colleague=colleague, proposer_day=MON, proposer_part="AM",
        colleague_day=MON, colleague_part="PM", message="School run")


def test_the_reason_box_is_a_field_labelled_with_who_hears_it(gp_client, gp_user):
    PracticeSettings.load()
    me = make_clinician("Casey Stone", user=gp_user)
    _swap(make_clinician("Blake Rowe"), me)
    html = gp_client.get("/me/").content.decode()
    assert 'class="inline-form"' in html and 'class="inline-input"' in html
    assert 'placeholder="Reason for declining (optional)"' in html
    assert 'aria-label="Reason for declining (optional) — sent to Blake Rowe"' in html


def test_the_admins_reason_box_is_labelled_too(admin_client):
    """It had no label of any kind — a placeholder only."""
    PracticeSettings.load()
    swap = _swap(make_clinician("Blake Rowe"), make_clinician("Casey Stone"))
    swap.status = SwapRequest.Status.ACCEPTED
    swap.save()
    html = admin_client.get("/requests/").content.decode()
    assert 'aria-label="Reason for declining (optional) — sent to Blake Rowe and Casey Stone"' in html


def test_the_reason_box_looks_like_every_other_field():
    """It shares the field rule (font, --field-border, padding) rather than
    copying it; its own rule only lays it out."""
    from tests.test_css_cascade import RULES
    looks = [r for r in RULES if r.selector == ".inline-input" and "border" in r.declarations]
    assert len(looks) == 1
    assert looks[0].declarations == rule(".field select").declarations
    assert rule(".inline-input:focus").declarations["border-color"] == "var(--accent)"


def test_a_row_of_buttons_wraps_rather_than_squeezes():
    """Seen at 390px: without a wrap the reason box shrank against Accept
    and pushed Decline underneath itself."""
    assert rule(".form-actions").declarations["flex-wrap"] == "wrap"
