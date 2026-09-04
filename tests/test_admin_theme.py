"""The admin wears the app's colours, derived — never typed.

Unfold wants two eleven-shade scales. `primary` is generated around
--accent so shade 600 IS the accent; `base` is anchored on the app's
neutrals. Both are asserted AA on the roles unfold uses them for, in both
themes (unfold's dark chrome uses base-900 as its ground).
"""

import re
from pathlib import Path

import pytest
import unfold

from rota import palette
from rota.admin_theme import base, primary, token

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"]
UNFOLD_CSS = (Path(unfold.__file__).resolve().parent
             / "static" / "unfold" / "css" / "styles.css")


def test_primary_600_is_the_accent():
    assert primary()["600"].lower() == token("--accent").lower()


@pytest.mark.parametrize("scale", [primary, base])
def test_each_scale_has_eleven_shades_getting_darker(scale):
    s = scale()
    assert list(s) == WEIGHTS
    lightness = [palette.srgb_to_oklch(s[w])[0] for w in WEIGHTS]
    assert lightness == sorted(lightness, reverse=True), "shades must darken with weight"


def test_base_anchors_are_the_apps_neutrals():
    s = base()
    assert s["50"].lower() == token("--ground").lower()
    assert s["900"].lower() == token("--ink").lower()
    assert s["500"].lower() == token("--muted").lower()


def test_text_and_button_roles_clear_aa_in_the_light_theme():
    p, b = primary(), base()
    assert palette.contrast_ratio("#FFFFFF", p["600"]) >= 4.5, "white on a primary button"
    assert palette.contrast_ratio(b["700"], b["50"]) >= 4.5, "default text on the ground"
    assert palette.contrast_ratio(b["900"], "#FFFFFF") >= 7, "important text on a card"


def test_text_roles_clear_aa_in_the_dark_theme():
    b = base()
    assert palette.contrast_ratio(b["300"], b["900"]) >= 4.5, "default text on the dark ground"
    assert palette.contrast_ratio(b["100"], b["900"]) >= 7, "important text on the dark ground"


def test_the_admin_stylesheet_carries_no_colour_literals():
    css = (ROOT / "static" / "admin" / "rota-admin.css").read_text()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.findall(r"#[0-9A-Fa-f]{3,8}\b|\brgba?\(|\bhsla?\(", css)


def test_the_theme_bridge_names_both_keys_and_guards_storage():
    js = (ROOT / "static" / "admin" / "theme-bridge.js").read_text()
    assert '"rota-theme"' in js and '"adminTheme"' in js
    assert "try" in js and "catch" in js


def test_unfold_declares_font_sans_inside_at_layer_theme():
    """rota-admin.css overrides --font-sans on a bare, unlayered :root —
    that only wins the cascade because unfold's own declaration sits
    inside an @layer theme block, which Tailwind gives lower precedence
    than unlayered rules regardless of source order or specificity. If a
    future unfold build moves --font-sans out of @layer theme (or drops
    the layer), our override would stop winning silently — no page
    errors, the font just reverts. A simple brace-depth scan finds
    @layer theme's own extent and checks --font-sans is declared inside
    it, at the same nesting depth (not inside some nested block)."""
    css = UNFOLD_CSS.read_text()
    start = css.index("@layer theme")
    brace_start = css.index("{", start)
    depth = 0
    end = None
    for i in range(brace_start, len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    assert end is not None, "could not find the closing brace of @layer theme"
    assert "--font-sans:" in css[brace_start:end]


@pytest.mark.django_db
def test_the_admin_page_carries_the_derived_colours_and_the_apps_font(admin_client):
    html = admin_client.get("/admin/").content.decode()
    assert "--color-primary-600" in html
    assert "fonts.css" in html and "rota-admin.css" in html and "theme-bridge.js" in html
