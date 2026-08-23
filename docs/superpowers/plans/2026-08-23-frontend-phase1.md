# Frontend Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the rota app a real design system — tokens, type scale, component vocabulary, a generated 40-tint session palette, and dark mode — applied across all 14 templates, changing no application logic.

**Architecture:** One Python module is the single source of truth for the session palette (OKLCH maths → sRGB hex, contrast-verified); it drives the model's colour choices, the migration, and the CSS custom properties emitted into every page. Presentation lives in three hand-written stylesheets (tokens, components, screens) loaded from `base.html`. No build step.

**Tech Stack:** Django 5.2 templates, hand-written CSS with custom properties, Plus Jakarta Sans via Google Fonts, pure-stdlib Python for colour maths. **No new dependencies.**

**Spec:** `docs/superpowers/specs/2026-08-23-frontend-phase1-design.md` — read it before starting any task.

## Global Constraints

- **No new dependencies.** No Tailwind, no node, no preprocessor, no colour library. Colour maths is stdlib-only (`math`).
- **No application logic changes.** Views, services and models are untouched except the `SessionType.colour` migration (Task 2).
- **The existing 214 tests must pass UNMODIFIED.** They are the regression net for this restyle. In particular do not disturb: the `mine`, `closed` and `draft` CSS classes; `colspan="2"` on merged duty days; session codes rendered as text; clinician names; form field `name` attributes; the `with <partner>` tooltip text; the strings `Request leave`, `Propose swap`, `behind target`, `No clinician profile`, `Log in`.
- **The grid stays a `<table>`.** It is tabular data; this is the accessible choice and keeps those tests meaningful.
- **Dark mode resolves in three states.** `:root` defines the complete light palette; `@media (prefers-color-scheme: dark)` redefines **only tokens**, guarded as `:root:not([data-theme="light"])`; `:root[data-theme="dark"]` redefines them again. No colour may be declared solely inside a media or `[data-theme]` block. `body` sets an explicit background from a token.
- **Accessibility:** every text/background pair meets WCAG AA (≥4.5:1) including all 40 session tints in both themes; visible keyboard focus on every interactive element; `prefers-reduced-motion` respected.
- Tokens only — no component stylesheet may hard-code a colour.
- Run `pytest -q` before every commit: all pass, 0 warnings. End commit messages with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

## File Structure

```
rota/palette.py                 CREATE  OKLCH maths, 40-tint table, contrast, nearest-match
rota/templatetags/__init__.py   CREATE  (package marker)
rota/templatetags/design.py     CREATE  {% palette_css %} tag
rota/models/catalog.py          MODIFY  SessionType.colour -> choices; +legacy_colour
rota/migrations/00NN_*.py       CREATE  schema + data migration for the above

static/css/tokens.css           CREATE  chrome tokens, type scale, space, dark mode, reset
static/css/components.css       CREATE  buttons, forms, tables, chips, badges, modal, nav
static/css/screens.css          CREATE  per-screen layout (grid, reports, schedule)
static/rota.css                 DELETE  (superseded; base.html stops loading it)

templates/base.html             MODIFY  fonts, three stylesheets, palette tag, nav w/ active state
templates/registration/login.html  MODIFY  currently unstyled
templates/rota/grid.html        MODIFY  chips, sticky header, density
templates/rota/my_schedule.html MODIFY
templates/rota/fill.html        MODIFY
templates/rota/inbox.html       MODIFY
templates/rota/leave_form.html  MODIFY
templates/rota/swap_form.html   MODIFY
templates/rota/report_*.html    MODIFY  (4 files)
templates/rota/_cell_form.html  MODIFY  (htmx partial)
templates/rota/_daynote_form.html  MODIFY  (htmx partial)
templates/rota/_locum_form.html MODIFY  (htmx partial)

tests/test_palette.py           CREATE  maths, contrast, nearest-match
tests/test_palette_migration.py CREATE  legacy hex -> tint mapping
tests/test_design_tag.py        CREATE  {% palette_css %} output
```

---

### Task 1: The palette module

**Files:**
- Create: `rota/palette.py`, `tests/test_palette.py`

**Interfaces:**
- Produces:
  - `HUES: list[tuple[str, float]]` — 20 `(name, hue_degrees)` pairs, hues 18° apart starting at 18.
  - `TONES: tuple[str, str]` — `("soft", "strong")`.
  - `Tint` dataclass: `key: str`, `label: str`, `bg: str`, `fg: str`, `dark_bg: str`, `dark_fg: str` (all `#rrggbb`).
  - `TINTS: dict[str, Tint]` — 40 entries keyed `f"{hue}-{tone}"` e.g. `"teal-soft"`.
  - `TINT_CHOICES: list[tuple[str, str]]` — Django choices, `(key, label)`, ordered as `HUES` × `TONES`.
  - `oklch_to_hex(L: float, C: float, H: float) -> str`
  - `hex_to_rgb(value: str) -> tuple[float, float, float]` — 0–1 floats.
  - `relative_luminance(rgb: tuple[float, float, float]) -> float` — WCAG.
  - `contrast_ratio(hex_a: str, hex_b: str) -> float`
  - `nearest_tint(hex_value: str) -> str` — returns a `TINTS` key; used by the migration.
  - `DEFAULT_TINT: str` — `"slate-soft"`.

- [ ] **Step 1: Write the failing tests**

`tests/test_palette.py`:
```python
import pytest

from rota import palette


def test_forty_tints_generated():
    assert len(palette.TINTS) == 40
    assert len(palette.HUES) == 20
    assert set(palette.TONES) == {"soft", "strong"}


def test_tint_keys_are_hue_tone():
    assert "teal-soft" in palette.TINTS
    assert "teal-strong" in palette.TINTS
    for key, tint in palette.TINTS.items():
        hue, tone = key.rsplit("-", 1)
        assert tone in palette.TONES
        assert tint.key == key


def test_every_tint_is_valid_hex():
    for tint in palette.TINTS.values():
        for value in (tint.bg, tint.fg, tint.dark_bg, tint.dark_fg):
            assert value.startswith("#") and len(value) == 7
            int(value[1:], 16)  # raises if not hex


def test_every_tint_meets_aa_contrast_in_both_themes():
    failures = []
    for key, tint in palette.TINTS.items():
        light = palette.contrast_ratio(tint.fg, tint.bg)
        dark = palette.contrast_ratio(tint.dark_fg, tint.dark_bg)
        if light < 4.5:
            failures.append(f"{key} light {light:.2f}")
        if dark < 4.5:
            failures.append(f"{key} dark {dark:.2f}")
    assert not failures, "tints below AA: " + ", ".join(failures)


def test_contrast_ratio_known_values():
    assert palette.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.05)
    assert palette.contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0, abs=0.01)


def test_oklch_to_hex_is_deterministic_and_in_gamut():
    a = palette.oklch_to_hex(0.94, 0.045, 180)
    b = palette.oklch_to_hex(0.94, 0.045, 180)
    assert a == b
    assert a.startswith("#") and len(a) == 7


def test_nearest_tint_maps_similar_colours_together():
    # The v1 default (a light blue) must land on a blue-ish soft tint.
    key = palette.nearest_tint("#8ecae6")
    assert key in palette.TINTS
    assert key.endswith("-soft")
    # A near-identical colour maps to the same tint.
    assert palette.nearest_tint("#8fcbe7") == key


def test_nearest_tint_distinguishes_far_apart_colours():
    assert palette.nearest_tint("#c1121f") != palette.nearest_tint("#2d6a4f")


def test_nearest_tint_handles_malformed_input():
    assert palette.nearest_tint("") == palette.DEFAULT_TINT
    assert palette.nearest_tint("not-a-colour") == palette.DEFAULT_TINT
    assert palette.nearest_tint("#fff") == palette.DEFAULT_TINT  # short form unsupported


def test_tint_choices_shape():
    assert len(palette.TINT_CHOICES) == 40
    keys = [k for k, _ in palette.TINT_CHOICES]
    assert keys == list(palette.TINTS)
    for key, label in palette.TINT_CHOICES:
        assert label and label != key  # human-readable, e.g. "Teal — soft"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_palette.py -q`
Expected: `ModuleNotFoundError: No module named 'rota.palette'`

- [ ] **Step 3: Implement**

`rota/palette.py`:
```python
"""The session-type colour palette.

Single source of truth for the 40 session tints: 20 hue families x 2 tones,
generated in OKLCH so every tint sits in the same perceptual band and the set
reads as one family rather than 40 unrelated colours.

Each tint carries a background and a foreground for both themes. Foregrounds
are darkened (light theme) or lightened (dark theme) along the same hue until
they meet WCAG AA against their background, so readability is guaranteed by
construction rather than by eye. `tests/test_palette.py` asserts it.

Pure stdlib: no colour library, per the project's no-new-dependencies rule.
"""

import math
from dataclasses import dataclass

# 20 hues, 18 degrees apart. Names are for the admin dropdown, so they are
# ordinary colour words rather than anything scientific.
HUES: list[tuple[str, float]] = [
    ("red", 18), ("vermilion", 36), ("orange", 54), ("amber", 72),
    ("yellow", 90), ("lime", 108), ("green", 126), ("emerald", 144),
    ("jade", 162), ("teal", 180), ("cyan", 198), ("sky", 216),
    ("azure", 234), ("blue", 252), ("indigo", 270), ("violet", 288),
    ("purple", 306), ("magenta", 324), ("pink", 342), ("slate", 360),
]

TONES: tuple[str, str] = ("soft", "strong")

# Background lightness/chroma per tone, per theme. Soft tints are the default
# for most session types; strong ones let a related type share a hue at a
# heavier weight (PMC-Urgent vs PMC-Routine).
_BG = {
    "soft":   {"light": (0.945, 0.040), "dark": (0.285, 0.045)},
    "strong": {"light": (0.880, 0.085), "dark": (0.360, 0.075)},
}
# Starting point for foregrounds; darkened/lightened until AA is met.
_FG_START = {"light": (0.42, 0.105), "dark": (0.90, 0.060)}

DEFAULT_TINT = "slate-soft"


# --------------------------------------------------------------------------
# colour maths
# --------------------------------------------------------------------------

def _linear_to_srgb(c: float) -> float:
    if c <= 0.0031308:
        return 12.92 * c
    return 1.055 * (c ** (1 / 2.4)) - 0.055


def _srgb_to_linear(c: float) -> float:
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def oklch_to_hex(L: float, C: float, H: float) -> str:
    """OKLCH -> sRGB hex, clamped into gamut."""
    h = math.radians(H)
    a = C * math.cos(h)
    b = C * math.sin(h)

    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b

    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3

    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s

    out = []
    for channel in (r, g, bl):
        v = _linear_to_srgb(max(0.0, min(1.0, channel)))
        out.append(max(0, min(255, round(v * 255))))
    return "#{:02x}{:02x}{:02x}".format(*out)


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    v = value.lstrip("#")
    if len(v) != 6:
        raise ValueError(f"expected #rrggbb, got {value!r}")
    return tuple(int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))


def relative_luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    la = relative_luminance(hex_to_rgb(hex_a))
    lb = relative_luminance(hex_to_rgb(hex_b))
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _readable_fg(bg_hex: str, hue: float, theme: str) -> str:
    """Walk lightness along the hue until AA is met against `bg_hex`."""
    L, C = _FG_START[theme]
    step = -0.04 if theme == "light" else 0.04
    for _ in range(24):
        candidate = oklch_to_hex(L, C, hue)
        if contrast_ratio(candidate, bg_hex) >= 4.5:
            return candidate
        L = max(0.0, min(1.0, L + step))
    # Fall back to the extreme that must work.
    return "#000000" if theme == "light" else "#ffffff"


@dataclass(frozen=True)
class Tint:
    key: str
    label: str
    bg: str
    fg: str
    dark_bg: str
    dark_fg: str


def _build() -> dict[str, Tint]:
    tints: dict[str, Tint] = {}
    for name, hue in HUES:
        for tone in TONES:
            lb_L, lb_C = _BG[tone]["light"]
            db_L, db_C = _BG[tone]["dark"]
            bg = oklch_to_hex(lb_L, lb_C, hue)
            dark_bg = oklch_to_hex(db_L, db_C, hue)
            key = f"{name}-{tone}"
            tints[key] = Tint(
                key=key,
                label=f"{name.capitalize()} — {tone}",
                bg=bg,
                fg=_readable_fg(bg, hue, "light"),
                dark_bg=dark_bg,
                dark_fg=_readable_fg(dark_bg, hue, "dark"),
            )
    return tints


TINTS: dict[str, Tint] = _build()
TINT_CHOICES: list[tuple[str, str]] = [(k, t.label) for k, t in TINTS.items()]


def nearest_tint(hex_value: str) -> str:
    """Closest tint to an arbitrary hex, by distance in OKLab-ish sRGB space.

    Used once, by the migration that converts free-form `SessionType.colour`
    values into palette keys. Malformed input falls back to DEFAULT_TINT.
    """
    try:
        target = hex_to_rgb(hex_value)
    except (ValueError, AttributeError):
        return DEFAULT_TINT

    best, best_d = DEFAULT_TINT, None
    for key, tint in TINTS.items():
        candidate = hex_to_rgb(tint.bg)
        d = sum((a - b) ** 2 for a, b in zip(target, candidate))
        if best_d is None or d < best_d:
            best, best_d = key, d
    return best
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_palette.py -q`
Expected: 10 passed. If `test_every_tint_meets_aa_contrast_in_both_themes` fails, the `_readable_fg` walk needs more range — widen `range(24)` or adjust `_FG_START`; do **not** weaken the 4.5 threshold.

- [ ] **Step 5: Run the full suite and commit**

```bash
pytest -q
git add rota/palette.py tests/test_palette.py
git commit -m "feat: generated 40-tint session palette with guaranteed AA contrast"
```

---

### Task 2: SessionType colour becomes a palette choice

**Files:**
- Modify: `rota/models/catalog.py` (the `colour` field on `SessionType`), `rota/admin.py`
- Create: `tests/test_palette_migration.py`, two migrations

**Interfaces:**
- Consumes: `rota.palette.TINT_CHOICES`, `nearest_tint`, `DEFAULT_TINT`, `TINTS`.
- Produces: `SessionType.colour` — `CharField(max_length=32, choices=TINT_CHOICES, default=DEFAULT_TINT)`; `SessionType.legacy_colour` — `CharField(max_length=7, blank=True, default="")` preserving the pre-migration hex; `SessionType.tint` property returning the `Tint` for the current key (falling back to `TINTS[DEFAULT_TINT]` if the key is unknown).

- [ ] **Step 1: Write the failing tests**

`tests/test_palette_migration.py`:
```python
import pytest

from rota import palette
from rota.models import SessionType
from tests.factories import make_session_type

pytestmark = pytest.mark.django_db


def test_colour_field_accepts_a_tint_key():
    st = make_session_type("Duty")
    st.colour = "teal-strong"
    st.full_clean()
    st.save()
    st.refresh_from_db()
    assert st.colour == "teal-strong"


def test_colour_field_rejects_raw_hex():
    st = make_session_type("Duty")
    st.colour = "#8ecae6"
    with pytest.raises(Exception):
        st.full_clean()


def test_tint_property_resolves():
    st = make_session_type("Duty")
    st.colour = "teal-strong"
    assert st.tint.bg == palette.TINTS["teal-strong"].bg
    assert st.tint.fg == palette.TINTS["teal-strong"].fg


def test_tint_property_falls_back_for_unknown_key():
    st = make_session_type("Duty")
    SessionType.objects.filter(pk=st.pk).update(colour="not-a-tint")
    st.refresh_from_db()
    assert st.tint is palette.TINTS[palette.DEFAULT_TINT]


def test_factory_default_is_a_valid_tint():
    st = make_session_type("Routine")
    assert st.colour in palette.TINTS
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_palette_migration.py -q`
Expected: FAIL — `colour` still accepts hex; no `tint` property.

- [ ] **Step 3: Implement the model change**

In `rota/models/catalog.py`, add near the top:
```python
from rota import palette
```
Replace the `colour` field on `SessionType` with:
```python
    colour = models.CharField(
        max_length=32, choices=palette.TINT_CHOICES, default=palette.DEFAULT_TINT,
        help_text="Session tint shown on the grid. All tints are contrast-checked.",
    )
    legacy_colour = models.CharField(
        max_length=7, blank=True, default="",
        help_text="The free-form hex this type used before the palette migration. "
                  "Kept for one release in case a mapping looks wrong.",
    )
```
And add to the model body:
```python
    @property
    def tint(self):
        """The Tint for this session type, falling back if the key is unknown."""
        return palette.TINTS.get(self.colour) or palette.TINTS[palette.DEFAULT_TINT]
```

Update `tests/factories.py`'s `make_session_type` default so it no longer sets a hex:
change `kw.setdefault("colour", "#8ecae6")` to `kw.setdefault("colour", palette.DEFAULT_TINT)`
(add `from rota import palette` to that file's imports).

- [ ] **Step 4: Create the migrations**

```bash
source .venv/bin/activate
python manage.py makemigrations rota -n session_tint_palette
python manage.py makemigrations rota --empty -n map_legacy_colours
```
Edit the empty one to:
```python
from django.db import migrations

from rota import palette


def to_tints(apps, schema_editor):
    SessionType = apps.get_model("rota", "SessionType")
    for st in SessionType.objects.all():
        old = (st.colour or "").strip()
        st.legacy_colour = old if old.startswith("#") else ""
        st.colour = palette.nearest_tint(old)
        st.save(update_fields=["colour", "legacy_colour"])


def back_to_hex(apps, schema_editor):
    SessionType = apps.get_model("rota", "SessionType")
    for st in SessionType.objects.all():
        if st.legacy_colour:
            st.colour = st.legacy_colour
            st.save(update_fields=["colour"])


class Migration(migrations.Migration):
    dependencies = [("rota", "<the session_tint_palette migration name>")]
    operations = [migrations.RunPython(to_tints, back_to_hex)]
```
(Replace the dependency with the real generated name.)

Add a migration test to `tests/test_palette_migration.py`:
```python
def test_legacy_hex_maps_to_a_sensible_tint():
    # The mapping function the data migration uses, exercised directly:
    # a red maps to a red-ish tint, a green to a green-ish one.
    red = palette.nearest_tint("#c1121f")
    green = palette.nearest_tint("#2d6a4f")
    assert red != green
    assert red in palette.TINTS and green in palette.TINTS
```

- [ ] **Step 5: Admin**

In `rota/admin.py`, add `"colour"` to `SessionTypeAdmin.list_display` and make
`legacy_colour` read-only:
```python
    list_display = ("name", "code", "category", "colour", "fairness_tracked",
                    "counts_toward_entitlement")
    readonly_fields = ("legacy_colour",)
```

- [ ] **Step 6: Migrate, run the suite, commit**

```bash
python manage.py migrate
pytest -q
git add -A
git commit -m "feat: session colours become contrast-checked palette tints"
```
Expected: all pass. Note `tests/test_grid_view.py` asserts on session **codes**, not colours, so it is unaffected.

---

### Task 3: Tokens, fonts, and the base template

**Files:**
- Create: `static/css/tokens.css`, `rota/templatetags/__init__.py`, `rota/templatetags/design.py`, `tests/test_design_tag.py`
- Modify: `templates/base.html`
- Delete: `static/rota.css` (only after `base.html` stops referencing it)

**Interfaces:**
- Consumes: `rota.palette.TINTS`.
- Produces: `{% load design %}{% palette_css %}` — a template tag emitting a `<style>` block defining, for every tint key, `--tint-<key>-bg` and `--tint-<key>-fg` under `:root`, plus dark-mode overrides in both the `prefers-color-scheme` and `[data-theme="dark"]` blocks. Marked safe via `django.utils.safestring.mark_safe`. Cached at module level (the palette never changes at runtime).

- [ ] **Step 1: Write the failing test**

`tests/test_design_tag.py`:
```python
import pytest
from django.template import Context, Template

from rota import palette

pytestmark = pytest.mark.django_db


def _render():
    return Template("{% load design %}{% palette_css %}").render(Context({}))


def test_emits_a_style_block():
    out = _render()
    assert out.strip().startswith("<style>")
    assert out.strip().endswith("</style>")


def test_defines_every_tint_in_both_themes():
    out = _render()
    for key, tint in palette.TINTS.items():
        assert f"--tint-{key}-bg: {tint.bg}" in out
        assert f"--tint-{key}-fg: {tint.fg}" in out
        assert tint.dark_bg in out
        assert tint.dark_fg in out


def test_dark_overrides_are_guarded_for_both_states():
    out = _render()
    assert "@media (prefers-color-scheme: dark)" in out
    assert ':root:not([data-theme="light"])' in out
    assert ':root[data-theme="dark"]' in out


def test_grid_page_includes_the_palette(admin_client):
    from rota.models import PracticeSettings
    from tests.factories import MON, make_clinician
    PracticeSettings.load()
    make_clinician()
    html = admin_client.get(f"/rota/?week={MON}").content.decode()
    assert "--tint-" in html
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_design_tag.py -q` — Expected: FAIL (`design` is not a registered tag library).

- [ ] **Step 3: Implement the tag**

`rota/templatetags/__init__.py`: empty file.

`rota/templatetags/design.py`:
```python
from django import template
from django.utils.safestring import mark_safe

from rota import palette

register = template.Library()


def _build_css() -> str:
    light = "\n".join(
        f"  --tint-{k}-bg: {t.bg}; --tint-{k}-fg: {t.fg};"
        for k, t in palette.TINTS.items()
    )
    dark = "\n".join(
        f"    --tint-{k}-bg: {t.dark_bg}; --tint-{k}-fg: {t.dark_fg};"
        for k, t in palette.TINTS.items()
    )
    return (
        "<style>\n:root {\n" + light + "\n}\n"
        "@media (prefers-color-scheme: dark) {\n"
        '  :root:not([data-theme="light"]) {\n' + dark + "\n  }\n}\n"
        ':root[data-theme="dark"] {\n' + dark.replace("    ", "  ") + "\n}\n"
        "</style>"
    )


_CSS = _build_css()  # the palette is static; build once at import


@register.simple_tag
def palette_css():
    return mark_safe(_CSS)
```

- [ ] **Step 4: Write `static/css/tokens.css`**

```css
/* Design tokens. Every colour in components.css and screens.css comes from
   here — no component may hard-code one. Dark mode redefines tokens only. */

:root {
  --accent:      #2F5D50;
  --accent-ink:  #FFFFFF;
  --accent-soft: #E4F2EC;
  --ink:         #1B1F27;
  --ink-soft:    #454C5A;
  --muted:       #8A91A0;
  --ground:      #FCFCFD;
  --surface:     #FFFFFF;
  --sunken:      #F7F8FA;
  --hairline:    #ECEDF1;

  --danger:      #A03A24;  --danger-soft:  #FDEAE6;
  --warning:     #855B1B;  --warning-soft: #FCF2E2;
  --ok:          #23604A;  --ok-soft:      #E4F2EC;

  --sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px; --sp-4: 16px;
  --sp-5: 24px; --sp-6: 32px; --sp-7: 48px;

  --fs-xs: 11.5px; --fs-sm: 12.5px; --fs-md: 13.5px;
  --fs-lg: 15px;   --fs-xl: 21px;   --fs-2xl: 30px;

  --r-sm: 6px; --r-md: 8px; --r-lg: 12px;
  --row-h: 34px;

  --font: "Plus Jakarta Sans", ui-sans-serif, system-ui, -apple-system,
          "Segoe UI", Roboto, sans-serif;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --accent:      #6FAE99;
    --accent-ink:  #10201A;
    --accent-soft: #1B2E28;
    --ink:         #E9EBF0;
    --ink-soft:    #B7BDC9;
    --muted:       #868D9D;
    --ground:      #131519;
    --surface:     #1A1D23;
    --sunken:      #21252C;
    --hairline:    #2C313A;
    --danger:      #F09A82;  --danger-soft:  #35201B;
    --warning:     #E0B451;  --warning-soft: #33290F;
    --ok:          #6FAE99;  --ok-soft:      #1B2E28;
  }
}

:root[data-theme="dark"] {
  --accent:      #6FAE99;
  --accent-ink:  #10201A;
  --accent-soft: #1B2E28;
  --ink:         #E9EBF0;
  --ink-soft:    #B7BDC9;
  --muted:       #868D9D;
  --ground:      #131519;
  --surface:     #1A1D23;
  --sunken:      #21252C;
  --hairline:    #2C313A;
  --danger:      #F09A82;  --danger-soft:  #35201B;
  --warning:     #E0B451;  --warning-soft: #33290F;
  --ok:          #6FAE99;  --ok-soft:      #1B2E28;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--ground);
  color: var(--ink-soft);
  font-family: var(--font);
  font-size: var(--fs-md);
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}

h1, h2, h3 { color: var(--ink); margin: 0; text-wrap: balance; letter-spacing: -.02em; }
h1 { font-size: var(--fs-2xl); font-weight: 800; }
h2 { font-size: var(--fs-xl); font-weight: 800; }
h3 { font-size: var(--fs-lg); font-weight: 700; }

a { color: var(--accent); }

:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: var(--r-sm); }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; }
}
```

- [ ] **Step 5: Rewrite `templates/base.html`**

Keep every existing link, the `hx-headers` attribute, the messages loop and the
`content` block — the tests depend on them.

```html
{% load static %}{% load design %}
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}Rota{% endblock %}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap">
<link rel="stylesheet" href="{% static 'css/tokens.css' %}">
<link rel="stylesheet" href="{% static 'css/components.css' %}">
<link rel="stylesheet" href="{% static 'css/screens.css' %}">
{% palette_css %}
<script src="{% static 'htmx.min.js' %}" defer></script>
</head>
<body hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>
<nav class="nav">
  <span class="nav-brand">Rota</span>
  <a href="/rota/" class="nav-link{% if request.path == '/rota/' %} is-active{% endif %}">Week</a>
  <a href="/me/" class="nav-link{% if request.path == '/me/' %} is-active{% endif %}">My schedule</a>
  {% if user.is_rota_admin %}
    <a href="/requests/" class="nav-link{% if request.path == '/requests/' %} is-active{% endif %}">Requests</a>
    <a href="/rota/fill/" class="nav-link{% if request.path == '/rota/fill/' %} is-active{% endif %}">Assisted fill</a>
  {% endif %}
  <a href="/reports/fairness/" class="nav-link{% if '/reports/' in request.path %} is-active{% endif %}">Reports</a>
  <span class="nav-spacer"></span>
  {% if user.is_authenticated %}
    <span class="nav-user">{{ user.email }}</span>
    <form method="post" action="/accounts/logout/">{% csrf_token %}<button class="btn btn-quiet">Log out</button></form>
  {% endif %}
</nav>
{% if messages %}
<div class="flashes">
  {% for m in messages %}<div class="flash">{{ m }}</div>{% endfor %}
</div>
{% endif %}
<main class="main">{% block content %}{% endblock %}</main>
</body>
</html>
```

Create empty placeholder files so the links resolve now and fill in Task 4:
```bash
touch static/css/components.css static/css/screens.css
```

- [ ] **Step 6: Remove the old stylesheet, run the suite, commit**

```bash
git rm static/rota.css
pytest -q
git add -A
git commit -m "feat: design tokens, Plus Jakarta Sans, palette CSS, restyled base shell"
```
Expected: all pass. `tests/test_accounts.py::test_login_page_renders` asserts
`b"Log in"` — unaffected.

---

### Task 4: Component stylesheet

**Files:**
- Modify: `static/css/components.css` (created empty in Task 3)

**Interfaces:**
- Consumes: tokens from `tokens.css`, tint variables from `{% palette_css %}`.
- Produces the class vocabulary every later task uses. **These exact names**:
  - Nav: `.nav`, `.nav-brand`, `.nav-link`, `.nav-link.is-active`, `.nav-spacer`, `.nav-user`
  - Layout: `.main`, `.page-head`, `.toolbar`, `.card`
  - Buttons: `.btn`, `.btn-primary`, `.btn-quiet`
  - Forms: `.field`, `.field label`, `.field-help`, `.field-error`, `.form-actions`
  - Tables: `.table` (report variant), `.table-grid` (dense grid variant)
  - Chips: `.chip`, `.chip.is-draft`, `.chip.is-empty`
  - Badges: `.badge`, `.badge.POSSIBLE`, `.badge.ADVERTISED`, `.badge.BOOKED`
  - Feedback: `.flashes`, `.flash`, `.warn`, `.daynote`, `.empty`, `.neg`
  - Modal: `#modal`
  - The pre-existing state classes `.mine`, `.closed`, `.draft`, `.unavail`, `.site-marker`, `.grid-header`, `.report`, `.request` must all keep working — tests and templates reference them.

- [ ] **Step 1: Write the four rules with real gotchas**

Most of this stylesheet is routine authoring from the tokens, but four rules have
traps in them. Use these verbatim:

```css
/* Chips take their colours from variables the template sets per cell, so the
   browser re-resolves them when the theme changes — no re-render needed. */
.chip {
  display: block;
  background: var(--chip-bg, var(--sunken));
  color: var(--chip-fg, var(--muted));
  border-radius: var(--r-md);
  padding: 5px 2px;
  font-size: var(--fs-xs);
  font-weight: 700;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.chip.is-empty { background: transparent; }
/* Drafts stay hatched so they read as provisional at a glance. */
.chip.is-draft {
  background-image: repeating-linear-gradient(45deg,
    transparent, transparent 4px,
    rgba(255,255,255,.55) 4px, rgba(255,255,255,.55) 8px);
}

/* Both the day header and the clinician column stay put while scrolling.
   The corner cell needs the higher z-index or the header wins over it. */
.table-grid { border-collapse: separate; border-spacing: 2px;
              font-variant-numeric: tabular-nums; width: 100%; }
.table-grid tbody tr { height: var(--row-h); }
.table-grid thead th { position: sticky; top: 0; z-index: 2;
                       background: var(--surface); }
.table-grid .grid-clin { position: sticky; left: 0; z-index: 1;
                         background: var(--surface); text-align: left; }
.table-grid thead .grid-clin { z-index: 3; }
```

Then write the rest of `static/css/components.css` covering every class listed
above, following these rules:
- Every colour comes from a token. No literals.
- `.badge.POSSIBLE` uses `--danger-soft`/`--danger`, `.ADVERTISED` uses
  `--warning-soft`/`--warning`, `.BOOKED` uses `--ok-soft`/`--ok`.
- `.chip` renders a session tint: `background: var(--chip-bg); color: var(--chip-fg);`
  where those two are set inline per cell by the template (Task 5).
- `.chip.is-draft` keeps the existing hatched treatment
  (`repeating-linear-gradient`) so drafts stay visually distinct.
- `.table-grid` gets `border-collapse: separate; border-spacing: 2px;` and
  `font-variant-numeric: tabular-nums`; rows are `height: var(--row-h)`.
- `.table-grid thead th` is `position: sticky; top: 0;` with a `--surface`
  background, and the first column `position: sticky; left: 0;` — so both the
  day header and the clinician column stay visible while scrolling.
- `.table` (reports) is roomier: `padding: var(--sp-3) var(--sp-4)` with a
  `--hairline` bottom border, tabular numerals.
- `.empty` is the empty-state treatment: centred, `--muted`, `--sp-6` padding.
- `.card` is `background: var(--surface); border: 1px solid var(--hairline);
  border-radius: var(--r-md);`.
- `#modal` keeps its fixed centring but gains `--surface`, `--r-lg`, a stronger
  shadow, and `#modal:empty { display: none; }` (existing behaviour).
- Keep `.grid-header`, `.report`, `.request` as aliases/compatible selectors so
  existing template markup does not break before Tasks 5–8 update it.

- [ ] **Step 2: Verify nothing regressed**

Run: `pytest -q`
Expected: all pass — CSS alone cannot break tests, but this confirms nothing in
Task 3 left the templates broken.

- [ ] **Step 3: Visually confirm the shell**

```bash
source .venv/bin/activate && python manage.py runserver 0.0.0.0:8000 &
curl -s localhost:8000/accounts/login/ | head -30
```
Confirm the stylesheets and the `<style>` palette block are all present in the
HTML, then stop the server. (A full visual pass happens in Task 9.)

- [ ] **Step 4: Commit**

```bash
git add static/css/components.css
git commit -m "feat: component vocabulary — buttons, forms, tables, chips, badges, modal"
```

---

### Task 5: The grid

**Files:**
- Modify: `templates/rota/grid.html`, `static/css/screens.css`

**Interfaces:**
- Consumes: `.table-grid`, `.chip`, `.badge`, `.warn`, `.daynote`, `.toolbar`,
  `.btn`; `SessionType.tint` (Task 2).
- Produces: `.grid-wrap` (the horizontally scrollable container), `.grid-day`,
  `.grid-part`, `.grid-clin`, `.grid-group`.

**This is the highest-risk template.** `tests/test_grid_view.py` asserts on
`ROUT`, `mine`, `closed`, `draft`, `<td colspan="`, `Advertised`, `Partner`
before `Salaried` ordering, `with Terry Trainee`, `Request leave`,
`Propose swap`. Preserve all of it.

- [ ] **Step 1: Confirm the current tests pass and note the baseline**

Run: `pytest tests/test_grid_view.py -q`
Expected: 9 passed. These same 9 must pass unmodified at the end of this task.

- [ ] **Step 2: Update the cell rendering to use the tint**

In `templates/rota/grid.html`, the cell currently does:
```html
{% if cell.entry %}style="background-color:{{ cell.entry.session_type.colour }}"{% endif %}
```
Replace the whole `<td>` with a chip-based cell (keeping every class the tests
assert on, and keeping `colspan` on merged pairs):
```html
  <td {% if cell.merged %}colspan="2"{% endif %}
      class="entry{% if cell.entry and not cell.entry.is_published %} draft{% endif %}{% if not cell.entry and cell.unavail %} unavail{% endif %}{% if cell.closed %} closed{% endif %}"
      {% if is_admin %}hx-get="/rota/cell/{{ row.clinician.id }}/{{ cell.day_str }}/{{ cell.part }}/"
      hx-target="#modal"{% endif %}
      title="{{ cell.entry.fill_reason|default:'' }} {{ cell.entry.note|default:'' }}{% if cell.partner %} with {{ cell.partner }}{% endif %}">
    {% if cell.entry %}
      <span class="chip{% if not cell.entry.is_published %} is-draft{% endif %}"
            style="--chip-bg: var(--tint-{{ cell.entry.session_type.tint.key }}-bg); --chip-fg: var(--tint-{{ cell.entry.session_type.tint.key }}-fg);">
        {{ cell.entry.session_type.code }}{% if cell.entry.site %}<span class="site-marker">{{ cell.entry.site.name|slice:":1" }}</span>{% endif %}
      </span>
    {% else %}<span class="chip is-empty">&nbsp;</span>{% endif %}
  </td>
```

**Two things about that markup matter and are easy to get wrong:**

1. Use `session_type.tint.key`, **not** `session_type.colour`. They are the same
   string for every valid key, but `.tint` falls back to the default tint when a
   row somehow holds an unknown key — and `--tint-<unknown>-bg` would not exist,
   rendering an unstyled chip. The property (Task 2) exists for exactly this.
2. Reference the **CSS variables**, never the resolved hex
   (`{{ ...tint.bg }}`). Baking the hex into the inline style would freeze the
   chip in light-mode colours — dark mode works precisely because the variable
   is re-resolved by the browser when the theme changes, with no re-render.

- [ ] **Step 3: Restyle the surrounding chrome**

Wrap the table in `<div class="grid-wrap">…</div>` (which carries
`overflow-x: auto`), convert `.grid-header` to `.toolbar` markup with `.btn`
classes on the buttons and links, and give the group rows `.grid-group`. Keep
the `Request leave` / `Propose swap` link text and the `has_clinician` guard
exactly as they are.

- [ ] **Step 4: Add the grid rules to `static/css/screens.css`**

`.grid-wrap { overflow-x: auto; }`, `.grid-day`/`.grid-part` header treatment
(day name at `--fs-lg`, part label at `--fs-xs` in `--muted`), `.grid-clin`
sticky first column, `.grid-group` as an uppercase `--muted` label row with
`--sp-4` top padding and no borders (Daylight's borderless grouping).

- [ ] **Step 5: Run the grid tests, then the suite**

Run: `pytest tests/test_grid_view.py -q` then `pytest -q`
Expected: 9 passed, then all pass. If a grid test fails, the markup lost
something it asserts on — restore it rather than editing the test.

- [ ] **Step 6: Commit**

```bash
git add templates/rota/grid.html static/css/screens.css
git commit -m "feat: restyle the rota grid — tinted chips, sticky headers, Ward Board density"
```

---

### Task 6: My schedule, request forms, and login

**Files:**
- Modify: `templates/rota/my_schedule.html`, `templates/rota/leave_form.html`,
  `templates/rota/swap_form.html`, `templates/registration/login.html`,
  `static/css/screens.css`

**Interfaces:**
- Consumes: `.card`, `.field`, `.btn`, `.table`, `.empty`, `.page-head`, `.chip`.
- Produces: `.auth-card` (the centred login panel), `.schedule-list`.

- [ ] **Step 1: Note the assertions these templates must preserve**

Run: `pytest tests/test_my_schedule.py tests/test_leave.py tests/test_swaps.py tests/test_accounts.py -q`
Expected: all pass. Assertions to preserve: `No clinician profile`,
`Terry Trainee`, `Other Person`, `Accept`, `ROUT`, `60`, `wedding`, `Log in`,
and every form field `name` attribute.

- [ ] **Step 2: Restyle My Schedule**

Wrap the leave-balance figures in a `.card` with the four numbers as a small
stat row; render upcoming sessions with `.table`; give the swaps-awaiting-response
block `.card` + `.btn` treatment; add an `.empty` state where the template
currently renders "No published sessions in the next four weeks." Keep the
no-clinician-profile message text exactly as-is.

- [ ] **Step 3: Restyle the two request forms**

Wrap each control in `.field` with a real `<label>`; add `.field-help` under the
swap form's existing explanatory paragraph; use `.btn.btn-primary` for submit.
Keep every `name=` attribute and the `{% csrf_token %}`.

- [ ] **Step 4: Restyle login**

Centre the form in an `.auth-card` on `--ground`, with the app name above it.
Keep the `{{ form.as_p }}` output (the test asserts `Log in`, and Django's error
rendering must keep working) — style it via `.auth-card form p` rather than
restructuring the form.

- [ ] **Step 5: Run those test files, then the suite, and commit**

```bash
pytest tests/test_my_schedule.py tests/test_leave.py tests/test_swaps.py tests/test_accounts.py -q
pytest -q
git add -A
git commit -m "feat: restyle my schedule, request forms, and login"
```

---

### Task 7: Reports, fill, and inbox

**Files:**
- Modify: `templates/rota/report_fairness.html`, `report_leave.html`,
  `report_staffing.html`, `report_trainees.html`, `fill.html`, `inbox.html`,
  `static/css/screens.css`

**Interfaces:**
- Consumes: `.table`, `.card`, `.btn`, `.field`, `.warn`, `.empty`, `.page-head`.
- Produces: `.report-nav` (the cross-links between the four reports),
  `.stat-row`, `.unfilled-group`.

- [ ] **Step 1: Note the assertions to preserve**

Run: `pytest tests/test_reports.py tests/test_reports_v2.py tests/test_fill_view.py tests/test_fill_view_grouping.py tests/test_leave.py -q`
Expected: all pass. Preserve: `behind target`, `next 26 weeks`, `next 1 weeks`,
`Alice Adams`, `Terry Trainee`, `ST2`, `>4<` and `>1<` (bare `<td>` numbers in
the trainee report — do **not** wrap those cells' numbers in a span),
`10 draft session(s) created`, `no eligible clinician`, `wedding`, and the
`<td>` structure the grouping test checks.

- [ ] **Step 2: Restyle the four reports**

Give each a `.page-head` (title + the existing cross-links as `.report-nav`),
`.table` for the data, `.neg` retained for negative balances, and an `.empty`
state where a report has no rows. The trainee report's expected/delivered
numbers stay as bare `<td>N</td>`.

- [ ] **Step 3: Restyle the fill screen**

`.card` around the date-range form with `.field` controls; the results summary as
a `.stat-row`; the grouped unfilled list as `.unfilled-group` rows rather than a
bare `<ul>`; `.btn-primary` for Run fill and Publish.

- [ ] **Step 4: Restyle the inbox**

Each pending request becomes a `.card` (keeping the existing `.request` class so
nothing depending on it breaks), with the overwrite preview in `.warn` styling
and approve/decline as `.btn-primary` / `.btn`. Add an `.empty` state — the
template already has "No pending leave requests."

- [ ] **Step 5: Run those files, the suite, and commit**

```bash
pytest tests/test_reports.py tests/test_reports_v2.py tests/test_fill_view.py tests/test_fill_view_grouping.py -q
pytest -q
git add -A
git commit -m "feat: restyle reports, assisted fill, and the requests inbox"
```

---

### Task 8: The htmx partials

**Files:**
- Modify: `templates/rota/_cell_form.html`, `_daynote_form.html`,
  `_locum_form.html`, `static/css/screens.css`

**Interfaces:**
- Consumes: `.field`, `.btn`, `.warn`, `#modal`.
- Produces: `.modal-head`, `.modal-body`, `.modal-actions`.

These three render **inside** `#modal` via htmx and have no `{% extends %}`, so
they inherit the page's tokens but need their own internal layout.

- [ ] **Step 1: Note the assertions to preserve**

Run: `pytest tests/test_edit_views.py tests/test_locums.py -q`
Expected: all pass. Preserve: every `name=` attribute (`session_type_id`,
`site_id`, `note`, `full_day`, `confirm`, `clinician_id`, `day`, `part`, `pk`,
`status`, `details`, `text`), the strings `not usually eligible`,
`Already booked`, `please double-check`, the `value="{{ req.pk }}"` hidden field,
and the `type="button"` on the Clear button (it prevents a double-fire).

- [ ] **Step 2: Restyle the three partials**

Give each a `.modal-head` (the "Dr X — Mon 20 AM" line), `.modal-body` with
`.field`-wrapped controls, and `.modal-actions` for the button row. Warnings
render in `.warn`. The ineligible-type markers ("(not usual)") stay as-is.

- [ ] **Step 3: Run those files, the suite, and commit**

```bash
pytest tests/test_edit_views.py tests/test_locums.py -q
pytest -q
git add -A
git commit -m "feat: restyle the htmx cell, day-note and locum editors"
```

---

### Task 9: Accessibility pass and visual verification

**Files:**
- Modify: `templates/rota/grid.html` (table semantics), `static/css/*.css` as needed
- Create: `tests/test_accessibility.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the failing tests**

`tests/test_accessibility.py`:
```python
import pytest

from rota.models import PracticeSettings
from tests.factories import MON, make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db


def test_grid_table_has_scope_and_caption(admin_client):
    PracticeSettings.load()
    c = make_clinician()
    make_entry(c, part="AM", session_type=make_session_type("Routine", code="ROUT"))
    html = admin_client.get(f"/rota/?week={MON}").content.decode()
    assert "<caption" in html
    assert 'scope="col"' in html
    assert 'scope="row"' in html


def test_pages_declare_a_language_and_viewport(client, db):
    html = client.get("/accounts/login/").content.decode()
    assert '<html lang="en">' in html
    assert 'name="viewport"' in html
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_accessibility.py -q`
Expected: the caption/scope test FAILS (the grid has neither today).

- [ ] **Step 3: Add the table semantics**

In `templates/rota/grid.html`, add a visually-hidden caption and scopes:
```html
<caption class="visually-hidden">Rota for the week of {{ monday|date:"j F Y" }}</caption>
```
Add `scope="col"` to the day and part header cells, `scope="row"` to the
clinician `<th>` cells, and `scope="colgroup"` where a day header spans AM+PM.
Add to `components.css`:
```css
.visually-hidden {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
```

- [ ] **Step 4: Run the accessibility tests and the full suite**

Run: `pytest tests/test_accessibility.py -q` then `pytest -q`
Expected: all pass, 0 warnings.

- [ ] **Step 5: Manual visual verification — required, and recorded**

Start the server, log in as an admin, and check **every** screen in **both**
themes at **two** widths (desktop ~1440px, phone ~390px):

```bash
source .venv/bin/activate
python manage.py runserver 0.0.0.0:8000
```

Screens: login, grid, my schedule, assisted fill, requests inbox, leave form,
swap form, all four reports, and the three modals (cell, day note, locum) opened
from the grid. Toggle dark mode via the OS setting, and separately by setting
`data-theme="dark"` on `<html>` in devtools — **both** paths must work, since
they are different CSS states.

Look specifically for: text that vanished (a colour defined only inside a media
block), the page body borrowing the host background, a silent font fallback
(Plus Jakarta Sans not loading), horizontal scrolling on the page body rather
than inside `.grid-wrap`, invisible keyboard focus, and chips whose text is
unreadable on their tint.

Record the outcome per screen in the implementation report. Fix anything found
before committing.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: grid table semantics, visually-hidden helper, accessibility tests"
```

---

## Final verification (after all tasks)

- [ ] `pytest -q` — all pass, 0 warnings. The original 214 tests must be
      **unmodified**: confirm with
      `git diff <base>..HEAD --stat -- tests/` that only the new test files
      (`test_palette.py`, `test_palette_migration.py`, `test_design_tag.py`,
      `test_accessibility.py`) and `tests/factories.py`'s one-line default
      change appear.
- [ ] `python manage.py makemigrations --check --dry-run` — no changes detected.
- [ ] Grep for hard-coded colours in the component/screen stylesheets:
      `grep -nE "#[0-9a-fA-F]{3,6}" static/css/components.css static/css/screens.css`
      should return nothing — every colour comes from a token.
- [ ] Use superpowers:verification-before-completion, then
      superpowers:finishing-a-development-branch.

