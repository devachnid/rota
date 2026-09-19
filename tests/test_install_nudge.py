"""The offer to add Rota to the home screen, on Android and iOS.

Chrome on Android shows its own install bar on heuristics a site cannot see
or steer; what it does guarantee is a `beforeinstallprompt` event once the
site is installable and not yet installed. The script keeps that event and
shows a card built like the passkey nudge; "Add" hands the event back to
Chrome, which puts up the real install sheet. iOS never fires the event and
has no sheet a page can open — the only way onto the home screen is the
Share sheet — so there the same card shows those steps instead of Add. As
with passkeys, the browser half has no automated test — a reviewer reads it
and Tom drives it on staging — so what is pinned here is the markup it
needs and the guards it must carry.
"""

from pathlib import Path

import pytest

from rota.models import PracticeSettings

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[1]


def _script() -> str:
    return (ROOT / "static" / "js" / "install.js").read_text()


def test_the_script_loads_once_from_the_base_template(gp_client, client):
    """On the login page too: the event fires early, and a listener that is
    not there when it does never hears it."""
    PracticeSettings.load()
    pages = (gp_client.get("/rota/"), gp_client.get("/me/"), client.get("/accounts/login/"))
    for resp in pages:
        assert resp.status_code == 200
        assert resp.content.decode().count("js/install.js") == 1


def test_a_signed_in_page_carries_the_nudge_hidden_until_chrome_offers(gp_client):
    PracticeSettings.load()
    html = gp_client.get("/rota/").content.decode()
    assert 'id="install-nudge" style="display:none"' in html
    assert 'id="install-nudge-add"' in html and 'id="install-later"' in html
    assert "Add Rota to your home screen" in html and "Not now" in html
    # The iOS steps travel hidden in the same card; the script reveals them.
    assert 'id="install-nudge-how" hidden' in html
    assert "Add to Home Screen" in html


def test_the_login_page_has_no_nudge(client):
    """Nobody is asked to install a site they have not signed in to."""
    html = client.get("/accounts/login/").content.decode()
    assert "install-nudge" not in html


def test_the_nudge_ids_stay_distinct_from_the_passkey_ones(gp_client):
    PracticeSettings.load()
    html = gp_client.get("/rota/").content.decode()
    for element_id in ("install-nudge", "install-nudge-add", "install-later",
                       "passkey-nudge", "passkey-nudge-add", "passkey-later"):
        assert html.count(f'id="{element_id}"') == 1, element_id


def test_the_script_offers_only_where_chrome_has_offered_or_on_ios():
    """The card is revealed in one function, called from the
    beforeinstallprompt handler and from the iOS branch and nowhere else —
    so desktop Chrome (its address-bar icon) and an app that is already
    installed never see it."""
    src = _script()
    assert "beforeinstallprompt" in src
    assert src.count('style.display = ""') == 1
    reveal = src[:src.index('style.display = ""')]
    assert "function show()" in reveal, "the reveal lives in show()"
    assert src.count("show()") == 3, "defined once, called from the handler and from iOS"
    handler = src[src.index("beforeinstallprompt"):src.index("appinstalled")]
    assert "show()" in handler
    ios_branch = src[src.index("if (ios)"):]
    assert "show()" in ios_branch


def test_on_ios_the_steps_replace_the_add_button():
    """iOS fires no event and has no sheet to open: the card shows the Share
    sheet steps and hides Add. Every iOS shape is recognised, including an
    iPad passing itself off as a Mac; a page already on the home screen is
    turned away by Safari's own flag as well as the media query."""
    src = _script()
    assert "/iPhone|iPad|iPod/.test(navigator.userAgent)" in src
    assert 'navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1' in src
    assert "navigator.standalone === true" in src
    ios_branch = src[src.index("if (ios)"):]
    assert '"install-nudge-add").hidden = true' in ios_branch
    assert '"install-nudge-how").hidden = false' in ios_branch


def test_the_script_hands_the_install_back_to_chrome_and_then_stands_down():
    src = _script()
    assert ".prompt()" in src                    # Add → Chrome's own install sheet
    assert "appinstalled" in src                 # installed elsewhere → the card goes


def test_not_now_snoozes_per_browser_and_standalone_never_asks():
    src = _script()
    assert "rota-install-snooze" in src
    assert "display-mode: standalone" in src
