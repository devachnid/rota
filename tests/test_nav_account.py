"""The desktop header: destinations, then one account menu.

It was eleven controls at one weight — brand, seven links, Theme, Feedback,
a 27-character email carrying a stray browser underline, and Log out — and
it wrapped to two rows below ~890px. Now everyone's four destinations come
first, a rota admin's three tools after a divider, then Feedback and a menu
named for whoever is signed in, holding Account, Theme and Log out.
"""

from pathlib import Path

import pytest
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from rota.context_processors import waiting
from rota.models import PracticeSettings
from tests.factories import make_clinician

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[1]
MENUS_JS = (ROOT / "static" / "js" / "menus.js").read_text()


def _nav(html):
    return html[html.index('<nav class="nav">'):html.index("</nav>")]


def _menu(nav):
    return nav[nav.index('<details class="nav-account">'):nav.index("</details>")]


def test_the_menu_is_named_for_the_clinician_signed_in(gp_client, gp_user):
    PracticeSettings.load()
    make_clinician("Tom Hodges", user=gp_user)
    nav = _nav(gp_client.get("/me/").content.decode())
    assert "Account menu for </span>Tom Hodges</summary>" in nav


def test_a_login_with_no_clinician_is_named_by_the_start_of_its_email(admin_client):
    """The whole address would push an admin's header to wrap below
    1080px; it is in the menu instead."""
    PracticeSettings.load()
    nav = _nav(admin_client.get("/rota/day/").content.decode())
    assert "Account menu for </span>admin</summary>" in nav
    assert "admin@example.com" in _menu(nav)


def test_account_theme_and_log_out_are_in_the_menu_and_feedback_is_not(gp_client, gp_user):
    PracticeSettings.load()
    make_clinician("Tom Hodges", user=gp_user)
    nav = _nav(gp_client.get("/me/").content.decode())
    menu = _menu(nav)
    for inside in ('href="/accounts/account/"', 'id="theme-toggle"', "Log out", "gp@example.com"):
        assert inside in menu, inside
    assert 'id="feedback-open"' in nav and 'id="feedback-open"' not in menu
    # The email lives in the menu only — no bare, underlined link in the bar.
    assert nav.count("gp@example.com") == 1


def test_everyones_destinations_come_before_the_admin_tools(admin_client, gp_client):
    PracticeSettings.load()
    nav = _nav(admin_client.get("/rota/day/").content.decode())
    order = [nav.index(f">{label}") for label in
             ("Week", "Day", "My schedule", "Reports", "Requests", "Assisted fill", "Admin")]
    assert order == sorted(order)
    assert nav.index("Reports") < nav.index('class="nav-divider"') < nav.index("Requests")
    gp_nav = _nav(gp_client.get("/rota/day/").content.decode())
    assert "nav-divider" not in gp_nav and "Requests" not in gp_nav


def test_signed_out_there_is_no_menu_but_the_theme_toggle_stays(client):
    nav = _nav(client.get("/accounts/login/").content.decode())
    assert "nav-account" not in nav
    assert 'id="theme-toggle" class="btn btn-quiet"' in nav


def test_naming_the_person_costs_no_query_of_its_own(gp_user):
    """The processor already read the clinician row for the swap count; the
    name comes out of that same query."""
    make_clinician("Tom Hodges", user=gp_user)
    request = RequestFactory().get("/me/")
    request.user = gp_user
    with CaptureQueriesContext(connection) as queries:
        out = waiting(request)
    assert out["signed_in_as"] == "Tom Hodges"
    assert len(queries) == 2  # the clinician row, the swaps waiting for them


def test_the_menus_close_on_an_outside_click_and_on_escape():
    """A <details> opens and closes without script; what it does not do is
    close when you have finished with it."""
    assert "details.nav-account" in MENUS_JS and "details.tabbar-more" in MENUS_JS
    assert '"click"' in MENUS_JS and '"Escape"' in MENUS_JS
    assert ".focus()" in MENUS_JS, "Escape hands focus back to the toggle"


def test_the_script_loads_on_every_page(gp_client, client):
    PracticeSettings.load()
    for resp in (gp_client.get("/me/"), client.get("/accounts/login/")):
        assert resp.content.decode().count("js/menus.js") == 1
