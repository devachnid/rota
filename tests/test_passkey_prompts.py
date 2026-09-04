"""Passkeys offered without being asked for. The login page arms conditional
mediation and every signed-in page carries a one-time card offering to
enrol this device — both are the script's doing, so what is pinned here is
the markup it needs and the timer that mops up after it. The browser half
itself has no automated test: a reviewer reads it, and Tom drives it on
staging."""

from pathlib import Path

import pytest

from rota.models import PracticeSettings

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[1]


def test_the_script_loads_once_from_the_base_template(gp_client, client):
    PracticeSettings.load()
    pages = (gp_client.get("/rota/"), gp_client.get("/accounts/account/"),
             client.get("/accounts/login/"))
    for resp in pages:
        assert resp.status_code == 200
        assert resp.content.decode().count("js/passkeys.js") == 1


def test_a_signed_in_page_carries_the_nudge_hidden_until_the_script_decides(gp_client):
    PracticeSettings.load()
    html = gp_client.get("/rota/").content.decode()
    assert 'id="passkey-nudge" style="display:none"' in html
    assert '<div class="flash" role="status">' in html         # the success line is announced
    assert 'id="passkey-nudge-add"' in html and 'id="passkey-later"' in html
    assert 'data-options-url="/accounts/passkeys/register/options/"' in html
    assert 'data-register-url="/accounts/passkeys/register/"' in html
    assert "Sign in faster next time." in html and "Not now" in html
    assert 'name="csrfmiddlewaretoken"' in html      # the script reads the token from the form


def test_the_login_page_has_no_nudge_and_keeps_what_the_script_needs(client):
    html = client.get("/accounts/login/").content.decode()
    assert "passkey-nudge" not in html
    assert 'id="passkey-login"' in html and 'name="username"' in html
    assert '<form method="post" id="login-form">' in html   # the script reads the token from it


def test_the_account_page_keeps_its_ids_distinct_from_the_nudge(gp_client):
    html = gp_client.get("/accounts/account/").content.decode()
    for element_id in ("passkey-add", "passkey-form", "passkey-error", "passkey-nudge",
                       "passkey-nudge-add", "passkey-nudge-form", "passkey-nudge-error"):
        assert html.count(f'id="{element_id}"') == 1, element_id


def test_a_clearsessions_timer_ships_with_the_other_units():
    service = (ROOT / "deploy" / "rota-clearsessions.service").read_text()
    timer = (ROOT / "deploy" / "rota-clearsessions.timer").read_text()
    assert "manage.py clearsessions" in service and "EnvironmentFile=/etc/rota.env" in service
    assert "OnCalendar=" in timer and "WantedBy=timers.target" in timer
    assert "rota-clearsessions.timer" in (ROOT / "README.md").read_text()
