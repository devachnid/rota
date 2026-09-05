"""The Feedback control is on every signed-in page and nowhere else, and the
modal it opens exists exactly once — in base.html, no longer in the grid."""

import re
from pathlib import Path

import pytest

from tests.test_css_cascade import rule

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parents[1]
MODAL = re.compile(r'id="modal"')
TRIGGER = 'hx-get="/feedback/form/"'


def test_a_signed_in_page_has_one_modal_and_two_ways_to_open_the_form(gp_client):
    html = gp_client.get("/rota/day/").content.decode()
    assert len(MODAL.findall(html)) == 1
    assert 'id="feedback-open"' in html
    assert html.count(TRIGGER) == 2  # the desktop nav and the More sheet
    assert html.count('hx-target="#modal"') >= 2


def test_the_grid_no_longer_carries_its_own_modal(admin_client):
    from rota.models import PracticeSettings
    PracticeSettings.load()
    html = admin_client.get("/rota/").content.decode()
    assert len(MODAL.findall(html)) == 1
    assert 'id="modal"' not in (ROOT / "templates/rota/grid.html").read_text()


def test_the_login_page_has_neither(client):
    html = client.get("/accounts/login/").content.decode()
    assert "feedback-open" not in html and 'id="modal"' not in html and TRIGGER not in html


def test_the_more_sheet_button_closes_the_sheet_it_sits_in(gp_client):
    html = gp_client.get("/rota/day/").content.decode()
    sheet = html.split('class="tabbar-sheet"', 1)[1]
    assert TRIGGER in sheet
    assert "removeAttribute('open')" in sheet


def test_the_control_is_as_quiet_as_the_theme_toggle():
    # Same rule as #theme-toggle: a nav control, not a page action.
    assert rule("#feedback-open").declarations["font-size"] == "var(--fs-xs)"
    assert rule("#theme-toggle").declarations["font-size"] == "var(--fs-xs)"


def test_the_radio_row_is_a_flex_row_and_the_fieldset_draws_no_box():
    assert rule(".radio-row").declarations["display"] == "flex"
    assert rule("fieldset.field").declarations["border"] == "0"
    assert rule(".field legend").declarations["font-weight"] == "700"
