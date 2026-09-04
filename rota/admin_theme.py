"""The admin's colour scales, derived from the app's tokens.

Unfold takes two eleven-shade scales. Typing them would be a second palette
that drifts from the first, so both are computed: `primary` around
--accent (shade 600 is the accent itself; lighter shades are tinted
grounds, darker ones pressed states), `base` anchored on the app's
neutrals with the gaps interpolated in OKLCH. Read from tokens.css the way
scripts/make_icons.py reads it. Hex out — unfold converts.

Unfold has ONE base scale for both themes and uses base-900 as its dark
ground, so the dark-theme text roles reference the light scale's dark
end rather than a second scale (a narrowing of the spec, recorded here).
"""

import functools
import re
from pathlib import Path

from rota import palette

TOKENS = Path(__file__).resolve().parents[1] / "static" / "css" / "tokens.css"


@functools.lru_cache(maxsize=None)
def token(name):
    """A hex custom property from the light :root block of tokens.css."""
    css = TOKENS.read_text()
    light = css[css.index(":root {"):css.index("@media")]
    match = re.search(rf"{re.escape(name)}:\s*(#[0-9A-Fa-f]{{6}})", light)
    if not match:
        raise LookupError(f"{name} is not in the light :root block of tokens.css")
    return match.group(1)


# Lightness per shade, and how much of the accent's chroma each keeps: the
# ends of the scale are grounds and near-blacks, which want less colour.
_PRIMARY_L = {"50": .97, "100": .94, "200": .88, "300": .79, "400": .68,
              "500": .56, "700": .36, "800": .30, "900": .245, "950": .17}
_PRIMARY_C = {"50": .25, "100": .35, "200": .50, "300": .70, "400": .90,
              "500": 1.0, "700": .95, "800": .85, "900": .70, "950": .55}

_BASE_ANCHORS = {"50": "--ground", "100": "--sunken", "200": "--hairline",
                 "400": "--field-border", "500": "--muted",
                 "700": "--ink-soft", "900": "--ink"}


def _ordered(scale):
    return {w: scale[w] for w in sorted(scale, key=int)}


def primary(request=None):
    accent = token("--accent")
    _, chroma, hue = palette.srgb_to_oklch(accent)
    scale = {w: palette.oklch_to_hex(_PRIMARY_L[w], chroma * _PRIMARY_C[w], hue)
             for w in _PRIMARY_L}
    scale["600"] = accent
    return _ordered(scale)


def _between(a_hex, b_hex):
    la, ca, ha = palette.srgb_to_oklch(a_hex)
    lb, cb, hb = palette.srgb_to_oklch(b_hex)
    return palette.oklch_to_hex((la + lb) / 2, (ca + cb) / 2, (ha + hb) / 2)


def base(request=None):
    scale = {w: token(name) for w, name in _BASE_ANCHORS.items()}
    scale["300"] = _between(scale["200"], scale["400"])
    scale["600"] = _between(scale["500"], scale["700"])
    scale["800"] = _between(scale["700"], scale["900"])
    l, c, h = palette.srgb_to_oklch(scale["900"])
    scale["950"] = palette.oklch_to_hex(max(l - 0.06, 0.0), c, h)
    return _ordered(scale)
