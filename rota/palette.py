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
    ("purple", 306), ("magenta", 324), ("pink", 342), ("rose", 360),
]

TONES: tuple[str, str] = ("soft", "strong")

# The neutral pair, which is deliberately NOT in HUES: a neutral is the absence
# of a hue, not another position on the ring, and pretending otherwise is how
# this palette previously ended up with a family called "slate" sitting at 360
# degrees — a red-pink that rendered #ffe2ec while its name promised grey.
# That family is now named "rose", which is what it is, and the grey it was
# impersonating is generated here instead.
#
# Not a dead grey. The chroma below is a whisper of the accent's own hue, so
# the neutral reads as chosen rather than as an absence of decision, the same
# bias the chrome palette in tokens.css carries. It is far under CHROMA_FLOOR,
# so the palette classifies its own neutral as a neutral — which is what makes
# nearest_tint() able to map a grey here without a special case.
NEUTRAL = "neutral"
NEUTRAL_HUE = 173.19  # --accent #2F5D50 in OKLCH
_NEUTRAL_C = {"light": 0.008, "dark": 0.009}
# Slightly more than the background carries, so the text is legibly of the same
# family without becoming a colour. Still an order of magnitude under the
# hue tints' foreground chroma.
_NEUTRAL_FG_C = 0.012

# Background lightness/chroma per tone, per theme. Soft tints are the default
# for most session types; strong ones let a related type share a hue at a
# heavier weight (PMC-Urgent vs PMC-Routine).
_BG = {
    "soft":   {"light": (0.945, 0.040), "dark": (0.285, 0.045)},
    "strong": {"light": (0.880, 0.085), "dark": (0.360, 0.075)},
}
# Starting point for foregrounds; darkened/lightened until AA is met.
_FG_START = {"light": (0.42, 0.105), "dark": (0.90, 0.060)}

DEFAULT_TINT = f"{NEUTRAL}-soft"

# Below this OKLCH chroma an input is a neutral — a grey, black or white — and
# its hue angle is not a colour, it is floating-point residue. `#cccccc` and
# `#ffffff` both report a hue of ~89.9 deg purely because the LMS matrix rows
# sum to 1.0 only to ten decimal places; assigning them a hue family on the
# strength of that would be inventing information. Anything under the floor
# gets DEFAULT_TINT instead.
#
# 0.02 is where a single sRGB channel pushed ~16/255 away from neutral lands
# (#908080 is C=0.0196, #f0f0ff is C=0.0200) — the smallest deviation that
# reads as a tint rather than as rounding. It leaves real colours untouched:
# the least saturated genuine colour in the practice's data and in the test
# corpus is #023047 at C=0.062, three times the floor, and it sits at half the
# chroma of the palette's own faintest tint (soft backgrounds are built at
# C=0.040), so nothing that could itself be a palette colour is rejected.
CHROMA_FLOOR = 0.02


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


def srgb_to_oklch(hex_value: str) -> tuple[float, float, float]:
    """sRGB hex -> (L, C, H). The inverse of `oklch_to_hex` above.

    The two matrices here are the 3x3 inverses of the two in `oklch_to_hex`;
    they agree with a Gauss-Jordan inversion of those exact coefficients to
    within 1e-8. `test_srgb_to_oklch_round_trips_oklch_to_hex` pins that down
    against the real generator, and
    `test_srgb_to_oklch_matches_published_srgb_primaries` checks it against
    published OKLab values so the pair cannot agree on being wrong together.

    H is degrees in [0, 360). It is only meaningful when C is non-trivial —
    for a neutral, a and b are both ~1e-10 and the angle is noise. Callers
    must gate on CHROMA_FLOOR before believing it.

    Raises ValueError on anything that is not #rrggbb.
    """
    lin_r, lin_g, lin_b = (_srgb_to_linear(c) for c in hex_to_rgb(hex_value))

    l = 0.4122214708 * lin_r + 0.5363325363 * lin_g + 0.0514459929 * lin_b
    m = 0.2119034982 * lin_r + 0.6806995451 * lin_g + 0.1073969566 * lin_b
    s = 0.0883024619 * lin_r + 0.2817188376 * lin_g + 0.6299787005 * lin_b

    # Signed cube root: the forward direction cubes, and near-black channels
    # can land a hair below zero, where ** (1/3) would raise.
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in (l, m, s))

    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    b = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_

    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360.0


def hue_distance(a: float, b: float) -> float:
    """Shortest distance between two hue angles, in degrees.

    The wheel wraps, so 350 and 10 are 20 apart, not 340. Computing this as a
    plain subtraction is what makes a colour just past 0 deg — a crimson, say —
    look 340-odd degrees from the families sitting at the top of the wheel,
    which is precisely where several of the practice's colours live.
    """
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def relative_luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    la = relative_luminance(hex_to_rgb(hex_a))
    lb = relative_luminance(hex_to_rgb(hex_b))
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _readable_fg(bg_hex: str, hue: float, theme: str, chroma: float | None = None) -> str:
    """Walk lightness along the hue until AA is met against `bg_hex`.

    `chroma` overrides the default foreground chroma. The neutral pair needs
    it: left at the hue-tint default the text would be generated at the same
    saturation as every other family, and a grey chip would carry deep green
    text. A neutral's foreground has to be neutral too.
    """
    L, C = _FG_START[theme]
    if chroma is not None:
        C = chroma
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
    # Neutral first: it is DEFAULT_TINT, so it heads the admin dropdown.
    for name, hue, neutral in (
        (NEUTRAL, NEUTRAL_HUE, True),
        *((n, h, False) for n, h in HUES),
    ):
        for tone in TONES:
            lb_L, lb_C = _BG[tone]["light"]
            db_L, db_C = _BG[tone]["dark"]
            fg_C = None
            if neutral:
                lb_C, db_C = _NEUTRAL_C["light"], _NEUTRAL_C["dark"]
                fg_C = _NEUTRAL_FG_C
            bg = oklch_to_hex(lb_L, lb_C, hue)
            dark_bg = oklch_to_hex(db_L, db_C, hue)
            key = f"{name}-{tone}"
            tints[key] = Tint(
                key=key,
                label=f"{name.capitalize()} — {tone}",
                bg=bg,
                fg=_readable_fg(bg, hue, "light", fg_C),
                dark_bg=dark_bg,
                dark_fg=_readable_fg(dark_bg, hue, "dark", fg_C),
            )
    return tints


TINTS: dict[str, Tint] = _build()
TINT_CHOICES: list[tuple[str, str]] = [(k, t.label) for k, t in TINTS.items()]


def nearest_tint(hex_value: str) -> str:
    """Closest tint to an arbitrary hex, by hue family then tone-by-lightness.

    Used once, by the migration that converts free-form `SessionType.colour`
    values into palette keys. Malformed input falls back to DEFAULT_TINT.

    Strategy: convert the source to OKLCH and pick the hue family whose
    declared angle in HUES is the smallest *angular* distance away, then within
    that family pick the tone whose background lightness best matches the
    source colour's luminance.

    Comparing hue angles is the whole point. An earlier version scored families
    by sRGB distance to the tint backgrounds instead; because every background
    sits at L~0.94 or 0.88, that distance was dominated by lightness and hue
    barely registered, so a saturated red landed on amber.

    Inputs below CHROMA_FLOOR have no hue worth preserving and go to the
    neutral family — still tone-by-lightness, so a pale grey lands on
    neutral-soft and a dark one on neutral-strong. Anything that is not a
    #rrggbb value falls back to DEFAULT_TINT.
    """
    try:
        _, chroma, hue = srgb_to_oklch(hex_value)
        target_luminance = relative_luminance(hex_to_rgb(hex_value))
    except (ValueError, AttributeError, TypeError):
        return DEFAULT_TINT

    family = (NEUTRAL if chroma < CHROMA_FLOOR
              else min(HUES, key=lambda nh: hue_distance(hue, nh[1]))[0])

    # Within the family, pick the tone whose background lightness is closer
    # to the source's luminance.
    return min(
        (f"{family}-{tone}" for tone in TONES),
        key=lambda k: abs(relative_luminance(hex_to_rgb(TINTS[k].bg)) - target_luminance),
    )
