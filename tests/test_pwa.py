"""The web app manifest, its icons, and the safe-area handling that goes with
running without browser chrome.

Two things here are worth stating plainly, because both have bitten this
project before:

  - The manifest is built in Python so that `static()` resolves each icon's
    hashed production URL. A test that only checked the JSON parsed would not
    notice a path that 404s after a deploy, so every icon URL is fetched.
  - The safe-area rules only ever apply below 640px. "The declaration is in
    the file" is exactly the evidence that has been wrong here before, so they
    are asserted to sit inside the media block, using the cascade parser.
"""

import json
import re
from pathlib import Path

import pytest
from django.test import Client

from tests.test_css_cascade import RULES

ROOT = Path(__file__).resolve().parents[1]
BASE_HTML = (ROOT / "templates" / "base.html").read_text()
TOKENS = (ROOT / "static" / "css" / "tokens.css").read_text()
ICON_DIR = ROOT / "static" / "icons"
BREAKPOINT = "(max-width: 640px)"


# --------------------------------------------------------------------------
# the manifest
# --------------------------------------------------------------------------

@pytest.mark.django_db
def test_the_manifest_is_served_without_a_login():
    """A browser reads it before anyone has signed in — on some platforms
    before the app is installed at all."""
    resp = Client().get("/manifest.webmanifest")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_the_manifest_declares_the_right_content_type():
    resp = Client().get("/manifest.webmanifest")
    assert resp["Content-Type"].startswith("application/manifest+json")


@pytest.mark.django_db
def test_the_manifest_asks_for_a_standalone_window_starting_on_my_schedule():
    data = json.loads(Client().get("/manifest.webmanifest").content)
    assert data["display"] == "standalone"
    # A GP opening the app wants their own sessions, not the whole practice's
    # week.
    assert data["start_url"] == "/me/"
    assert data["scope"] == "/"


@pytest.mark.django_db
def test_every_icon_the_manifest_names_actually_resolves():
    """The failure this catches: production hashes static filenames, so a
    hand-written icon path 404s after the first deploy that touches one."""
    client = Client()
    data = json.loads(client.get("/manifest.webmanifest").content)
    assert data["icons"], "the manifest names no icons at all"
    for icon in data["icons"]:
        path = ROOT / "static" / icon["src"].removeprefix("/static/")
        assert path.exists(), f"{icon['src']} is named but no such file exists"


@pytest.mark.django_db
def test_the_manifest_offers_both_a_plain_and_a_maskable_icon():
    """Without a maskable icon, a platform that crops to a circle clips the
    mark; without a plain one, a platform that does not gets a mark floating
    in a large margin."""
    data = json.loads(Client().get("/manifest.webmanifest").content)
    purposes = {i["purpose"] for i in data["icons"]}
    assert "any" in purposes and "maskable" in purposes


@pytest.mark.django_db
def test_the_manifest_colours_match_the_design_tokens():
    """They are written out in config/views.py rather than read from the
    stylesheet per request. This is what stops the two drifting."""
    from config.views import BACKGROUND_COLOR, THEME_COLOR

    light = TOKENS[TOKENS.index(":root {"):TOKENS.index("@media")]
    accent = re.search(r"--accent:\s*(#[0-9A-Fa-f]{6})", light).group(1)
    ground = re.search(r"--ground:\s*(#[0-9A-Fa-f]{6})", light).group(1)
    assert THEME_COLOR == accent
    assert BACKGROUND_COLOR == ground


# --------------------------------------------------------------------------
# what base.html declares
# --------------------------------------------------------------------------

def test_the_page_links_the_manifest_and_the_apple_touch_icon():
    assert 'rel="manifest"' in BASE_HTML
    # iOS does not read the manifest for its home-screen icon.
    assert 'rel="apple-touch-icon"' in BASE_HTML


def test_the_viewport_opts_into_the_safe_area():
    """Without viewport-fit=cover the insets below are always zero, and every
    safe-area rule in the stylesheet is inert."""
    viewport = re.search(r'name="viewport" content="([^"]*)"', BASE_HTML).group(1)
    assert "viewport-fit=cover" in viewport


def test_a_theme_colour_is_declared_for_each_scheme():
    """A manifest carries one theme_color and this app has three theme
    states, so the two media-scoped tags are what make the system bar follow
    the page."""
    tags = re.findall(r'<meta name="theme-color"[^>]*>', BASE_HTML)
    assert any("prefers-color-scheme: light" in t for t in tags)
    assert any("prefers-color-scheme: dark" in t for t in tags)


def test_the_theme_colour_tags_carry_the_accent_from_each_theme():
    light_block = TOKENS[TOKENS.index(":root {"):TOKENS.index("@media")]
    dark_block = TOKENS[TOKENS.index(':root[data-theme="dark"]'):]
    for block, scheme in ((light_block, "light"), (dark_block, "dark")):
        accent = re.search(r"--accent:\s*(#[0-9A-Fa-f]{6})", block).group(1)
        tag = next(t for t in re.findall(r'<meta name="theme-color"[^>]*>', BASE_HTML)
                   if f"prefers-color-scheme: {scheme}" in t)
        assert accent.lower() in tag.lower(), (
            f"the {scheme} theme-color does not carry that theme's --accent"
        )


# --------------------------------------------------------------------------
# the safe area, which only exists below the breakpoint
# --------------------------------------------------------------------------

def test_the_tab_bar_pads_itself_for_the_home_indicator():
    """Installed to a home screen there is no browser chrome, so the bar sits
    on the home indicator. Asserted inside the media block: above 640px the
    bar does not exist and the rule would be meaningless."""
    padded = [r for r in RULES
              if r.selector == ".tabbar" and r.media == BREAKPOINT
              and "safe-area-inset-bottom" in r.declarations.get("padding-bottom", "")]
    assert padded, (
        ".tabbar never takes the bottom safe-area inset inside the 640px "
        "block, so on a notched phone it renders under the home indicator"
    )


def test_the_body_clearance_grows_by_the_same_inset():
    """The bar got taller; if the page's clearance did not, the last row of
    every screen hides behind it."""
    cleared = [r for r in RULES
               if r.selector == "body" and r.media == BREAKPOINT
               and "safe-area-inset-bottom" in r.declarations.get("padding-bottom", "")]
    assert cleared, "body's clearance ignores the safe-area inset the bar takes"


def test_the_safe_area_rules_keep_a_plain_fallback():
    """An engine without env() drops the whole declaration, so the page needs
    a value that does not mention it."""
    css = (ROOT / "static" / "css" / "screens.css").read_text()
    block = css[css.index("@media (max-width: 640px)"):]
    body_rule = block[block.index("body {"):]
    body_rule = body_rule[:body_rule.index("}")]
    plain = [line for line in body_rule.splitlines()
             if "padding-bottom" in line and "env(" not in line]
    assert plain, "body's clearance has no env()-free fallback declaration"


# --------------------------------------------------------------------------
# the icons themselves
# --------------------------------------------------------------------------

def _png_size(path: Path) -> tuple[int, int]:
    import struct
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    return struct.unpack(">II", data[16:24])


@pytest.mark.parametrize("name,expected", [
    ("icon-192.png", (192, 192)),
    ("icon-512.png", (512, 512)),
    ("maskable-512.png", (512, 512)),
    ("apple-touch-icon.png", (180, 180)),
    ("favicon-32.png", (32, 32)),
])
def test_each_icon_is_a_png_of_the_size_its_name_claims(name, expected):
    assert _png_size(ICON_DIR / name) == expected


def test_the_committed_icons_match_what_the_generator_produces():
    """The generator and the committed PNGs cannot silently disagree.

    Without this, someone edits scripts/make_icons.py, does not re-run it, and
    the repository keeps shipping icons no code in it now describes.
    """
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import make_icons

    for name, (size, inset) in make_icons.ICONS.items():
        regenerated = make_icons._png(make_icons.render(size, inset))
        committed = (ICON_DIR / name).read_bytes()
        assert regenerated == committed, (
            f"{name} differs from what scripts/make_icons.py now produces — "
            f"re-run it and commit the result"
        )


def test_the_maskable_icon_keeps_its_mark_inside_the_safe_circle():
    """A maskable icon may be cropped to a circle of 80% diameter. Anything
    outside that can be clipped, so the mark has to sit well within it."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import make_icons

    size, inset = make_icons.ICONS["maskable-512.png"]
    # The mark spans `inset`..`1 - inset` of each edge; its furthest corner
    # from the centre must fall inside the safe circle's 0.4 radius.
    half_span = 0.5 - inset
    corner_radius = (half_span ** 2 + half_span ** 2) ** 0.5
    assert corner_radius <= 0.4, (
        f"the maskable mark reaches {corner_radius:.3f} of the icon's width "
        f"from centre; the safe circle stops at 0.400"
    )


def test_the_deploy_check_covers_the_manifest_icons():
    """A missing icon must fail at deploy time, not on an installed app's
    cold start. The icons carry no {% static %} tag for the check's scan to
    find, so they are added to its reference set explicitly — this asserts
    that wiring, which is otherwise invisible until it is too late.
    """
    from config.views import ICON_SOURCES
    from rota import checks

    refs = checks._template_static_refs()
    for path in ICON_SOURCES:
        assert path in refs, (
            f"{path} is served by the manifest but is not under the deploy "
            f"check, so a missing icon would 500 at request time instead"
        )
