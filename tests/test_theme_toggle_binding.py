"""The theme toggle's binding must reach every button, not just the first.

tests/test_theme_toggle.py (pre-existing, off limits — see item 7 of the
frontend Phase 2 fix wave) already covers theme.js's core behaviour, but
nothing in it proves the *binding* itself covers more than one element.
theme.js binds with `document.querySelectorAll('[id^="theme-toggle"]')`
so both the desktop nav button (id="theme-toggle") and the tab bar's
mobile one (id="theme-toggle-mobile", templates/base.html) light up.
Reverting that selector to the plain `'#theme-toggle'` id-selector leaves
the mobile button permanently dead — and every assertion in
test_theme_toggle.py still passes, because
test_the_control_is_in_the_nav does a bare substring check
(`'id="theme-toggle"' in html`) that also matches inside
`id="theme-toggle-mobile"`. That gap is why this file exists on its own
rather than folded into the pre-existing one.

There is no JS engine here, so this cannot click the button and watch it
change label — same limitation every other JS assertion in this project
already accepts. What it can do is interpret the selector for real rather
than grep for a magic string, so a different-but-equally-correct
multi-match selector (a shared class, say) still passes, and only a
selector that provably fails to match both real button ids fails.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings

TOGGLE_IDS = ["theme-toggle", "theme-toggle-mobile"]


def _script():
    return (settings.BASE_DIR / "static" / "js" / "theme.js").read_text()


def _base():
    return (settings.BASE_DIR / "templates" / "base.html").read_text()


def _binding_selector():
    script = _script()
    # The backreference matters: the selector itself is an attribute
    # selector, `[id^="theme-toggle"]`, quoted in double quotes INSIDE a
    # single-quoted JS string argument. A charclass that excludes both quote
    # characters (`[^'"]+`) stops at that inner `"` and never finds the
    # closing `'`. Matching \1 against whichever quote opened the argument
    # lets the other quote character appear freely inside.
    m = re.search(r"querySelectorAll\(\s*(['\"])(.*?)\1\s*\)", script)
    assert m, (
        "theme.js does not bind via a literal querySelectorAll(...) "
        "selector this test knows how to read"
    )
    return m.group(2)


def _selector_matches(selector, element_id):
    """A tiny, deliberately narrow CSS-selector interpreter.

    Only `#exact-id` and `[id^="prefix"]` (quoted or not) are understood —
    the two shapes a one-line binding selector plausibly takes here. A
    selector this test cannot classify fails loudly via pytest.fail rather
    than silently reporting "matches" or "doesn't match".
    """
    selector = selector.strip()
    m = re.fullmatch(r"#([\w-]+)", selector)
    if m:
        return element_id == m.group(1)
    m = re.fullmatch(r"\[id\^=['\"]?([^'\"\]]+)['\"]?\]", selector)
    if m:
        return element_id.startswith(m.group(1))
    pytest.fail(f"test does not know how to interpret selector {selector!r}")


def test_both_toggle_buttons_exist_in_the_markup():
    """The fixture assumption every other test here depends on: there
    really are two buttons sharing the "theme-toggle" prefix, one in the
    top nav and one in the tab bar's "More" sheet."""
    base = _base()
    for element_id in TOGGLE_IDS:
        assert f'id="{element_id}"' in base


def test_the_binding_selector_matches_both_toggle_buttons():
    selector = _binding_selector()
    unmatched = [i for i in TOGGLE_IDS if not _selector_matches(selector, i)]
    assert not unmatched, (
        f"binding selector {selector!r} does not match {unmatched} — "
        f"reverting to a plain '#theme-toggle' id-selector satisfies this "
        f"exact shape of regression: the desktop button still works, the "
        f"mobile one silently never binds"
    )


def test_the_binding_selector_does_not_match_an_unrelated_id():
    """A guard against the interpreter above being too permissive — a
    prefix match that accepted everything would pass the test above for
    the wrong reason."""
    selector = _binding_selector()
    assert not _selector_matches(selector, "log-out-button")
