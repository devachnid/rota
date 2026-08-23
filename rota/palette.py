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

    Soft tints are slightly preferred: when comparing candidates, strong tints
    must be noticeably closer to win.
    """
    try:
        target = hex_to_rgb(hex_value)
    except (ValueError, AttributeError):
        return DEFAULT_TINT

    best, best_d = DEFAULT_TINT, None
    for key, tint in TINTS.items():
        candidate = hex_to_rgb(tint.bg)
        d = sum((a - b) ** 2 for a, b in zip(target, candidate))
        # Prefer soft tints by penalizing strong ones
        if key.endswith("-strong"):
            d += 0.085
        if best_d is None or d < best_d:
            best, best_d = key, d
    return best
