"""The bottom tab bar, and proof that its rules are not inert.

Phase 1's repeat failure was CSS that looked right and never applied. The
tab bar is invisible above 640px by design, so "it is in the stylesheet" is
exactly the kind of evidence that has been wrong here before. These tests
assert the rules sit INSIDE the media query, using the cascade parser that
learned to read at-rules in Task 1.

What this cannot prove: that a browser paints a usable bar at 375px. That is
a live measurement, and it is still outstanding.
"""

import re
from pathlib import Path

import pytest

from tests.test_css_cascade import RULES, rule

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "templates" / "base.html").read_text()
COMPONENTS = (ROOT / "static" / "css" / "components.css").read_text()
SCREENS = (ROOT / "static" / "css" / "screens.css").read_text()

BREAKPOINT = "(max-width: 640px)"


def _rules_for(selector):
    return [r for r in RULES if r.selector == selector]


def test_the_bar_is_in_the_markup():
    assert 'class="tabbar"' in BASE


def test_the_bar_links_to_the_day_view():
    assert "/rota/day/" in BASE


def test_the_bar_is_hidden_by_default():
    """Above the breakpoint there is no tab bar at all, so its base rule must
    hide it rather than relying on the media query to do so."""
    base = [r for r in _rules_for(".tabbar") if r.media is None]
    assert base, ".tabbar has no top-level rule"
    assert any(r.declarations.get("display") == "none" for r in base)


def test_the_bar_is_revealed_only_inside_the_breakpoint():
    revealed = [r for r in _rules_for(".tabbar")
                if r.media == BREAKPOINT
                and r.declarations.get("display") not in (None, "none")]
    assert revealed, (
        ".tabbar is never shown inside the 640px media query — the rule is "
        "inert and the bar can never appear"
    )


def test_the_top_nav_is_hidden_inside_the_breakpoint():
    hidden = [r for r in _rules_for(".nav")
              if r.media == BREAKPOINT
              and r.declarations.get("display") == "none"]
    assert hidden, "the top nav is never hidden, so both navs show at once"


def test_the_body_clears_the_fixed_bar():
    """A fixed bar overlays the end of the page unless something reserves
    space for it."""
    padded = [r for r in RULES
              if r.media == BREAKPOINT
              and "padding-bottom" in r.declarations
              and r.selector in ("body", ".main")]
    assert padded, "nothing reserves space for the fixed bar; content is hidden behind it"


def test_touch_targets_are_large_enough():
    """WCAG 2.5.8 and plain usability: 44px."""
    sized = [r for r in RULES
             if r.selector.startswith(".tabbar")
             and ("min-height" in r.declarations or "height" in r.declarations)]
    assert sized, ".tabbar items have no height, so touch target size is unknowable"
    values = [r.declarations.get("min-height") or r.declarations.get("height")
              for r in sized]
    assert any(
        v and v.endswith("px") and int(re.sub(r"\D", "", v)) >= 44
        for v in values
    ), f"no tab bar rule reaches a 44px touch target: {values}"


def test_the_modal_stacks_above_the_tab_bar():
    """#modal and .tabbar are both position: fixed, so on a short landscape
    phone below the breakpoint they compete on z-index alone, regardless of
    where either sits in the DOM. .tabbar was z-index: 20 and #modal
    z-index: 10 — the bar painted over the modal's pinned Save/Cancel
    actions. The modal has to out-rank every z-index the bar ever declares,
    inside the media query or out."""
    modal_z = int(rule("#modal").declarations["z-index"])
    tabbar_z_values = [
        int(r.declarations["z-index"])
        for r in _rules_for(".tabbar")
        if "z-index" in r.declarations
    ]
    assert tabbar_z_values, ".tabbar declares no z-index; nothing to compare"
    assert modal_z > max(tabbar_z_values), (
        f"#modal z-index {modal_z} does not out-rank .tabbar's "
        f"{tabbar_z_values} — the bar can cover the modal"
    )


def test_there_is_exactly_one_width_breakpoint_in_the_project():
    """The spec allows one. More than one means someone invented a second
    mental model for narrow screens."""
    queries = set()
    for sheet in (COMPONENTS, SCREENS):
        queries.update(re.findall(r"@media\s*\(([^)]*width[^)]*)\)", sheet))
    assert queries == {"max-width: 640px"}, f"unexpected breakpoints: {queries}"


@pytest.mark.django_db
def test_the_more_menu_needs_no_javascript(admin_client):
    from rota.models import PracticeSettings
    PracticeSettings.load()
    html = admin_client.get("/rota/day/").content.decode()
    assert "<details" in html and "<summary" in html


def test_the_top_nav_wraps_rather_than_overflowing():
    """Between the 640px breakpoint and roughly 890px the desktop nav is the
    only navigation on screen, and its min-content width exceeds the viewport
    — brand, six links, the theme button, an email address and Log out. Left
    nowrap it pushed the whole page sideways on portrait tablets and
    half-screen windows. Measured at 700px before the fix: the document
    scrolled to 888px against a 685px viewport.
    """
    base = [r for r in _rules_for(".nav") if r.media is None]
    assert base, ".nav has no top-level rule"
    assert any(r.declarations.get("flex-wrap") == "wrap" for r in base), (
        ".nav does not wrap, so it overflows the viewport horizontally "
        "between the breakpoint and roughly 890px"
    )
