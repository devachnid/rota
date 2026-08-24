"""WCAG AA for the chrome palette — the half of the design system the tint
tests never covered.

`tests/test_palette.py` asserts AA for all 40 generated session tints. Nothing
asserted it for the hand-written tokens in `static/css/tokens.css`, and that is
exactly where the failure was: `--muted` shipped at #8A91A0, which measures
3.16 / 3.09 / 2.98 against the three grounds it is used on and is small text
everywhere it appears.

These tests read the stylesheet itself rather than a copy of its values, so a
token edited in the CSS is measured as edited. Every ratio comes from
`rota.palette.contrast_ratio`; none is asserted from judgement.
"""

import re
from pathlib import Path

import pytest

from rota import palette

CSS_DIR = Path(__file__).resolve().parents[1] / "static" / "css"

AA = 4.5  # every consumer of these tokens is small text (--fs-xs / --fs-sm)


# --------------------------------------------------------------------------
# reading the stylesheet
# --------------------------------------------------------------------------

def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _block(css: str, selector: str) -> str:
    """The body of the rule opened by `selector`, brace-matched."""
    i = css.index(selector)
    start = css.index("{", i)
    depth = 0
    for j in range(start, len(css)):
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return css[start + 1:j]
    raise AssertionError(f"unclosed block for {selector!r}")


def _colours(body: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z-]+):\s*(#[0-9A-Fa-f]{6})\s*;", body))


def _alphas(body: str) -> dict[str, tuple[tuple[int, int, int], float]]:
    """--name: rgb(R G B / A%) -> {name: ((r, g, b), alpha)}."""
    out = {}
    for name, r, g, b, a in re.findall(
        r"--([a-z-]+):\s*rgb\(\s*(\d+)\s+(\d+)\s+(\d+)\s*/\s*(\d+)%\s*\)\s*;", body
    ):
        out[name] = ((int(r), int(g), int(b)), int(a) / 100)
    return out


_TOKENS_CSS = _strip_comments((CSS_DIR / "tokens.css").read_text())

_BLOCKS = {
    "light": _block(_TOKENS_CSS, "\n:root {"),
    "dark (prefers-color-scheme)": _block(_TOKENS_CSS, ':root:not([data-theme="light"])'),
    "dark (data-theme)": _block(_TOKENS_CSS, ':root[data-theme="dark"]'),
}
THEMES = {name: _colours(body) for name, body in _BLOCKS.items()}
WASHES = {name: _alphas(body)["wash"] for name, body in _BLOCKS.items()}


# --------------------------------------------------------------------------
# 1. every chrome foreground on every ground it is actually used on
# --------------------------------------------------------------------------

# (foreground token, background token, where the pairing occurs). Each entry is
# a real pairing in components.css / screens.css / the templates, not a
# combinatorial sweep — a pair nothing renders would be a fake failure.
PAIRS = [
    ("ink", "ground", "h1/h2/h3 and .grid-day over the page ground"),
    ("ink", "surface", ".table th, .field label, .grid-clin, .stat-value in a .card"),
    ("ink", "sunken", ".table th over a .closed / .unavail cell"),
    ("ink", "accent-soft", ".flash, and .mine's clinician cell"),
    ("ink-soft", "ground", "body text"),
    ("ink-soft", "surface", ".btn, .nav-link, .report-nav a, card body text"),
    ("ink-soft", "sunken", ".btn:hover, .btn-quiet:hover"),
    ("muted", "ground", ".empty, .field-help, .stat-label on the page ground"),
    ("muted", "surface", ".nav-user, .btn-quiet, .grid-part, .grid-group td, .badge"),
    ("muted", "sunken", ".badge default, .closed body cells, .chip fallback fg"),
    ("accent", "ground", "a, .report-nav a:hover"),
    ("accent", "surface", ".nav-link.is-active, links in a card"),
    ("accent", "sunken", "links over a sunken cell"),
    ("accent-ink", "accent", ".btn-primary"),
    ("danger", "ground", ".neg, .warn, .field-error on the page ground"),
    ("danger", "surface", ".warn in a grid header, .field-error in a modal, .errorlist"),
    ("danger", "sunken", ".warn over a sunken cell"),
    ("danger", "danger-soft", ".badge.POSSIBLE"),
    ("warning", "surface", ".daynote in the grid header"),
    ("warning", "ground", ".daynote / warning text on the page ground"),
    ("warning", "warning-soft", ".badge.ADVERTISED"),
    ("ok", "ok-soft", ".badge.BOOKED"),
]


@pytest.mark.parametrize("theme", list(THEMES))
@pytest.mark.parametrize("fg,bg,where", PAIRS, ids=[f"{f}-on-{b}" for f, b, _ in PAIRS])
def test_chrome_pairs_meet_aa(theme, fg, bg, where):
    tokens = THEMES[theme]
    ratio = palette.contrast_ratio(tokens[fg], tokens[bg])
    assert ratio >= AA, (
        f"{theme}: --{fg} {tokens[fg]} on --{bg} {tokens[bg]} = {ratio:.2f}:1, "
        f"below AA {AA}:1 ({where})"
    )


def test_muted_specifically_clears_all_three_grounds_in_light_mode():
    """The regression that let #8A91A0 ship. Pinned with its own numbers."""
    light = THEMES["light"]
    for ground in ("surface", "ground", "sunken"):
        ratio = palette.contrast_ratio(light["muted"], light[ground])
        assert ratio >= AA, f"--muted on --{ground} = {ratio:.2f}:1"


def test_every_colour_token_is_defined_in_all_three_theme_blocks():
    """No colour may have its only definition inside a media or attribute
    block — a token defined only under prefers-color-scheme silently falls
    back to nothing for a reader who has toggled the theme explicitly."""
    names = {theme: set(_colours(body)) | set(_alphas(body))
             for theme, body in _BLOCKS.items()}
    base = names["light"]
    for theme, defined in names.items():
        assert defined == base, (
            f"{theme} defines {sorted(defined ^ base)} differently from bare :root"
        )


# --------------------------------------------------------------------------
# 2. the composited draft-chip case
# --------------------------------------------------------------------------

def _composite(wash: tuple[tuple[int, int, int], float], bg_hex: str) -> str:
    """Source-over alpha blend of `wash` onto `bg_hex`, per channel in sRGB.

    Browsers composite in sRGB by default, so this is the effective colour the
    chip's foreground is actually read against.
    """
    (wr, wg, wb), alpha = wash
    bg = [c * 255 for c in palette.hex_to_rgb(bg_hex)]
    out = [alpha * w + (1 - alpha) * b for w, b in zip((wr, wg, wb), bg)]
    return "#{:02x}{:02x}{:02x}".format(*[max(0, min(255, round(v))) for v in out])


def test_composite_is_source_over():
    assert _composite(((255, 255, 255), 1.0), "#000000") == "#ffffff"
    assert _composite(((255, 255, 255), 0.0), "#123456") == "#123456"
    assert _composite(((0, 0, 0), 0.5), "#ffffff") == "#808080"


@pytest.mark.parametrize("theme", list(THEMES))
def test_draft_chip_text_meets_aa_over_the_wash(theme):
    """`.chip.is-draft`'s hatch and `.site-marker`'s disc both lay --wash over
    the chip's tint background, with the chip's own tint foreground on top.

    This measures the worst case for both: text sitting fully over a washed
    stripe (the hatch) or over the marker disc. Text on the unwashed part of
    the chip is `tests/test_palette.py`'s case and is unaffected.

    The predecessor token --overlay-light stayed light in both themes, which
    in dark mode composited a dark chip up to mid-grey and dropped its light
    text to 1.76:1.
    """
    dark = theme != "light"
    wash = WASHES[theme]
    failures = []
    for key, tint in palette.TINTS.items():
        bg = tint.dark_bg if dark else tint.bg
        fg = tint.dark_fg if dark else tint.fg
        effective = _composite(wash, bg)
        ratio = palette.contrast_ratio(fg, effective)
        if ratio < AA:
            failures.append(f"{key} {fg} on {effective} = {ratio:.2f}")
    assert not failures, (
        f"{theme}: draft chip below AA over --wash: " + ", ".join(failures)
    )


@pytest.mark.parametrize("theme", list(THEMES))
def test_wash_moves_away_from_the_chip_background(theme):
    """The polarity rule the token exists to enforce: the wash must be lighter
    than a light chip and darker than a dark one, never the reverse."""
    dark = theme != "light"
    (rgb, _alpha) = WASHES[theme]
    wash_luminance = palette.relative_luminance(tuple(c / 255 for c in rgb))
    for key, tint in palette.TINTS.items():
        bg = tint.dark_bg if dark else tint.bg
        bg_luminance = palette.relative_luminance(palette.hex_to_rgb(bg))
        if dark:
            assert wash_luminance < bg_luminance, f"{theme}: wash not darker than {key}"
        else:
            assert wash_luminance > bg_luminance, f"{theme}: wash not lighter than {key}"


# --------------------------------------------------------------------------
# 3. the no-literals rule that keeps all of the above meaningful
# --------------------------------------------------------------------------

@pytest.mark.parametrize("sheet", ["components.css", "screens.css"])
def test_no_colour_literals_outside_tokens_css(sheet):
    """Contrast can only be audited from tokens.css if that is where every
    colour lives. The draft hatch was the one sanctioned literal; it now takes
    --wash, so there is no exception left."""
    css = _strip_comments((CSS_DIR / sheet).read_text())
    literals = re.findall(r"#[0-9A-Fa-f]{3,8}\b|\brgba?\(|\bhsla?\(", css)
    assert not literals, f"{sheet} contains colour literals: {literals}"


# --------------------------------------------------------------------------
# 5. non-text contrast (WCAG 1.4.11) for UI component boundaries
# --------------------------------------------------------------------------

# The text tests above all passed on a form whose fields were invisible: every
# label and value cleared AA, while the border that tells someone WHERE TO TYPE
# measured 1.17:1 against the field and 1.14:1 against the page. Contrast for
# text and contrast for a control's boundary are separate success criteria, and
# only the first was ever asserted. This is that gap.
NON_TEXT = 3.0  # WCAG 2.1 SC 1.4.11 Non-text Contrast

# (token, background token, where). The visible boundary of an input, select or
# textarea must be distinguishable from BOTH the control's own fill and the
# surface the control sits on — a border that only clears one of the two still
# leaves an edge that disappears on the other side.
BOUNDARY_PAIRS = [
    ("field-border", "surface", ".field input / select / textarea fill"),
    ("field-border", "ground", "the page behind a form on --ground"),
]


@pytest.mark.parametrize("theme", list(THEMES))
@pytest.mark.parametrize(
    "token,bg,where", BOUNDARY_PAIRS, ids=[f"{t}-vs-{b}" for t, b, _ in BOUNDARY_PAIRS]
)
def test_control_boundaries_meet_non_text_contrast(theme, token, bg, where):
    tokens = THEMES[theme]
    ratio = palette.contrast_ratio(tokens[token], tokens[bg])
    assert ratio >= NON_TEXT, (
        f"{theme}: --{token} {tokens[token]} on --{bg} {tokens[bg]} = "
        f"{ratio:.2f}:1, below WCAG 1.4.11's {NON_TEXT}:1 for a UI component "
        f"boundary ({where})"
    )


def test_form_controls_do_not_use_the_decorative_hairline_for_their_border():
    """--hairline is a divider between cards and table rows; at ~1.2:1 it is
    correct there and wrong on a control's edge. Pin the distinction so the
    two tokens cannot quietly converge again."""
    components = _strip_comments((CSS_DIR / "components.css").read_text())
    rule = _block(components, ".field input:not")
    assert "var(--field-border)" in rule, (
        "the .field control rule no longer takes its border from --field-border"
    )
    assert "var(--hairline)" not in rule, (
        "the .field control rule is back on --hairline, which fails WCAG 1.4.11"
    )
    for theme, tokens in THEMES.items():
        assert tokens["field-border"] != tokens["hairline"], (
            f"{theme}: --field-border and --hairline have converged on "
            f"{tokens['hairline']}; the boundary would fail 1.4.11 again"
        )
