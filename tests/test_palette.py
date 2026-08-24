import pytest

from rota import palette


def test_the_palette_is_twenty_hues_plus_a_neutral():
    """20 hue families x 2 tones, plus the neutral pair. The neutral is not in
    HUES on purpose: it is the absence of a hue, not another angle on the ring,
    and treating it as one is how the family at 360 degrees ended up named
    "slate" while rendering a pink."""
    assert len(palette.HUES) == 20
    assert set(palette.TONES) == {"soft", "strong"}
    assert palette.NEUTRAL not in dict(palette.HUES)
    assert len(palette.TINTS) == 20 * 2 + 2 == 42


def test_the_neutral_is_actually_neutral():
    """Its whole job. A tint that claims to be grey and is not is the defect
    this pair was added to fix, so measure the chroma rather than trusting the
    name — and measure the foreground too, since generating it at the hue
    tints' saturation would put deep green text on a grey chip."""
    for key in (f"{palette.NEUTRAL}-soft", f"{palette.NEUTRAL}-strong"):
        t = palette.TINTS[key]
        for label, value in (("bg", t.bg), ("fg", t.fg),
                             ("dark_bg", t.dark_bg), ("dark_fg", t.dark_fg)):
            _, chroma, _ = palette.srgb_to_oklch(value)
            assert chroma < palette.CHROMA_FLOOR, (
                f"{key}.{label} = {value} has chroma {chroma:.4f}, at or above "
                f"CHROMA_FLOOR {palette.CHROMA_FLOOR} — the palette would not "
                f"classify its own neutral as a neutral"
            )


def test_the_default_tint_is_the_neutral():
    """A session type with no colour chosen should not silently become pink."""
    assert palette.DEFAULT_TINT == f"{palette.NEUTRAL}-soft"
    _, chroma, _ = palette.srgb_to_oklch(palette.TINTS[palette.DEFAULT_TINT].bg)
    assert chroma < palette.CHROMA_FLOOR


def test_the_family_at_360_degrees_is_named_for_the_colour_it_renders():
    """It was "slate", which promised a grey and delivered #ffe2ec."""
    assert "rose" in dict(palette.HUES)
    assert "slate" not in dict(palette.HUES)
    _, chroma, hue = palette.srgb_to_oklch(palette.TINTS["rose-soft"].bg)
    assert chroma >= palette.CHROMA_FLOOR, "rose is a colour, not a neutral"
    assert palette.hue_distance(hue, 360) < 20


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


@pytest.mark.parametrize("hex_value,expected", [
    # (L, C, H) published by Björn Ottosson for the sRGB primaries. These are
    # an EXTERNAL reference, not values read back out of our own code, so they
    # pin the inverse to the real OKLab definition rather than to itself.
    ("#ff0000", (0.6279554, 0.2576833, 29.2338)),
    ("#00ff00", (0.8664396, 0.2948272, 142.4953)),
    ("#0000ff", (0.4520137, 0.3132143, 264.0520)),
])
def test_srgb_to_oklch_matches_published_srgb_primaries(hex_value, expected):
    L, C, H = palette.srgb_to_oklch(hex_value)
    assert L == pytest.approx(expected[0], abs=1e-6)
    assert C == pytest.approx(expected[1], abs=1e-6)
    assert H == pytest.approx(expected[2], abs=1e-3)


def test_srgb_to_oklch_round_trips_oklch_to_hex():
    """The inverse must undo the forward transform for in-gamut colours.

    L=0.6/C=0.10 is comfortably inside sRGB at every hue, so the only error
    left is 8-bit quantisation of the intermediate hex.
    """
    for hue in range(0, 360, 3):
        L, C, H = palette.srgb_to_oklch(palette.oklch_to_hex(0.6, 0.10, hue))
        assert L == pytest.approx(0.6, abs=0.005), hue
        assert C == pytest.approx(0.10, abs=0.005), hue
        assert palette.hue_distance(H, hue) < 1.0, hue


def test_srgb_to_oklch_rejects_malformed_input():
    with pytest.raises(ValueError):
        palette.srgb_to_oklch("#fff")
    with pytest.raises(ValueError):
        palette.srgb_to_oklch("not-a-colour")


@pytest.mark.parametrize("a,b,expected", [
    (350.0, 10.0, 20.0),    # wraps across 0 — the case a subtraction gets wrong
    (10.0, 350.0, 20.0),    # and symmetrically
    (0.0, 360.0, 0.0),      # same angle, named twice
    (5.0, 18.0, 13.0),      # no wrap needed
    (0.0, 180.0, 180.0),    # antipodal — the maximum
    (0.0, 181.0, 179.0),    # just past antipodal comes back down
])
def test_hue_distance_wraps_around_the_wheel(a, b, expected):
    assert palette.hue_distance(a, b) == pytest.approx(expected, abs=1e-9)


def test_nearest_tint_is_stable_for_near_identical_colours():
    assert palette.nearest_tint("#8ecae6") == palette.nearest_tint("#8fcbe7")


# Every expected key below was derived from the input's OKLCH hue angle and
# the declared angles in palette.HUES — NOT by running nearest_tint and
# pasting its answer back. The comment on each row carries the hue angle and
# the winning family's distance so the arithmetic can be re-checked by hand.
# HUES is 18 deg apart, so the winner is always within 9 deg.
@pytest.mark.parametrize("hex_value,expected_key", [
    # --- the practice's real pre-migration values ---
    ("#eb4034", "vermilion-strong"),  # H= 28.7 -> vermilion(36) +7.3 vs red(18) +10.7
    ("#eba134", "amber-strong"),      # H= 71.9 -> amber(72)     +0.1 vs orange(54) +17.9
    ("#8ecae6", "azure-strong"),      # H=228.7 -> azure(234)    +5.3 vs sky(216)  +12.7
    # --- reds: the end of the wheel the old code mangled worst ---
    ("#c1121f", "red-strong"),        # H= 25.9 -> red(18)       +7.9 vs vermilion(36) +10.1
    ("#ffadad", "red-strong"),        # H= 19.3 -> red(18)       +1.3 vs vermilion(36) +16.7
    # --- blues ---
    ("#023047", "azure-strong"),      # H=237.0 -> azure(234)    +3.0 vs blue(252)  +15.0
    ("#bde0fe", "blue-strong"),       # H=244.3 -> blue(252)     +7.7 vs azure(234) +10.3
    ("#a0c4ff", "blue-strong"),       # H=260.1 -> blue(252)     +8.1 vs indigo(270) +9.9
    # --- the rest of the wheel ---
    ("#ff7f00", "orange-strong"),     # H= 52.6 -> orange(54)    +1.4 vs vermilion(36) +16.6
    ("#2d6a4f", "jade-strong"),       # H=162.2 -> jade(162)     +0.2 vs teal(180) +17.8
    ("#caffbf", "emerald-soft"),      # H=140.2 -> emerald(144)  +3.8 vs green(126) +14.2
    ("#cdb4db", "purple-strong"),     # H=313.5 -> purple(306)   +7.5 vs magenta(324) +10.6
])
def test_nearest_tint_maps_by_hue_angle(hex_value, expected_key):
    """Exact keys, not hue-family sets. An over-broad assertion is what let the
    hue-blind version of this function ship: it scored families by sRGB
    distance to backgrounds that all sit at L~0.9, so lightness dominated and
    #eb4034 — an unmistakable red — came out as amber-strong.

    If a row here fails, work out which of the two is wrong before touching
    anything. The hue angle in the comment is the authority, not the code.
    """
    assert palette.nearest_tint(hex_value) == expected_key


@pytest.mark.parametrize("hex_value,expected_key", [
    ("#db2777", "rose-strong"),  # H=  0.6 -> rose(360) +0.6 vs red(18) +17.4
    ("#c2185b", "rose-strong"),  # H=  5.6 -> rose(360) +5.6 vs red(18) +12.4
    ("#ff1493", "rose-strong"),  # H=357.0 -> rose(360) +3.1 vs pink(342) +14.9
])
def test_nearest_tint_wraps_at_the_red_end_of_the_wheel(hex_value, expected_key):
    """The 0/360 seam. `slate` is declared at 360 deg, so a crimson a degree or
    two *past* zero is right next to it — but only if angular distance wraps.

    Computed as a plain `abs(H - hue)` subtraction, #db2777 (H=0.58) looks
    359.4 deg from slate and just 17.4 from red, so it lands on red-strong.
    That is the same class of error as the bug this replaces, and it is at the
    red end where several of the practice's colours live. These rows fail if
    the wrap is dropped.
    """
    assert palette.nearest_tint(hex_value) == expected_key


@pytest.mark.parametrize("hex_value,expected_key", [
    # Lightness still decides the tone; only the hue is meaningless. The
    # boundary sits between the two neutral backgrounds, #e8efec (L~0.945)
    # and #d2d9d7 (L~0.880) — white and near-white are closer to the first,
    # everything from mid-grey down to black is closer to the second.
    ("#ffffff", "neutral-soft"),
    ("#f7f8fa", "neutral-soft"),
    ("#cccccc", "neutral-strong"),
    ("#888888", "neutral-strong"),
    ("#000000", "neutral-strong"),
])
def test_nearest_tint_sends_neutrals_to_the_neutral_family(hex_value, expected_key):
    """A grey has no hue to preserve, so inventing one is a lie.

    Their measured chroma is ~1e-8 and their reported hue is pure
    floating-point residue — the direction of a vector with no length. With
    the constants `srgb_to_oklch` ships today #cccccc, #888888 and #ffffff all
    come out near H=89.9, for no reason other than where those rows round off;
    #000000 lands on exactly 0. An early version duly filed them under
    emerald, emerald, purple and green respectively. Which arbitrary angle
    they report is not a property of the colours and is not asserted anywhere
    — see `test_neutrals_really_do_report_a_meaningless_hue`.

    They now reach a real neutral rather than whatever DEFAULT_TINT happened
    to be, and they keep the tone step: a grey carries no hue but it does
    carry a lightness, and throwing that away too would map white and black
    onto the same chip.
    """
    assert palette.nearest_tint(hex_value) == expected_key


def test_neutrals_really_do_report_a_meaningless_hue():
    """Guards the premise of the chroma floor, so it cannot rot silently.

    The chroma is the whole claim, and it is the only thing asserted here. The
    angle these greys come back with is deliberately not asserted: it is the
    direction of a vector ~1e-8 long, so it is decided entirely by the last
    digits of the inverse-matrix constants in `srgb_to_oklch`. Those constants
    are inverses to ten decimal places; swap them for exactly-computed ones and
    the same three greys report 240.3, 186.2 and 187.1 degrees instead of all
    landing near 89.9. Pinning any of those numbers would turn a strictly
    correct tightening of the constants into a red test whose message blamed
    the hue code, which was never wrong. There is no hue here to be right
    about — only a chroma small enough that `nearest_tint` must refuse to look
    at the angle at all.
    """
    for grey in ("#cccccc", "#888888", "#ffffff"):
        _L, C, _H = palette.srgb_to_oklch(grey)
        assert C < 1e-6, (grey, C)


def test_chroma_floor_admits_genuinely_muted_colours():
    """The floor must catch greys without swallowing real, low-chroma colours.

    #023047 is the least saturated genuine colour in the corpus at C=0.062 —
    three times the floor. #908080 (one channel nudged 16/255) sits just under
    it, which is the boundary the value was chosen for.
    """
    assert palette.srgb_to_oklch("#023047")[1] > palette.CHROMA_FLOOR
    assert palette.nearest_tint("#023047") != palette.DEFAULT_TINT
    assert palette.srgb_to_oklch("#908080")[1] < palette.CHROMA_FLOOR


def test_nearest_tint_always_picks_the_closest_declared_hue():
    """Property check over the sRGB cube: the family nearest_tint returns must
    be the one whose declared angle is closest to the input's actual hue.

    HUES is 20 families evenly spaced 18 deg apart, so the winner can never be
    more than 9 deg away. The old implementation missed by up to 75.
    """
    angles = dict(palette.HUES)
    worst = 0.0
    for r in range(0, 256, 17):
        for g in range(0, 256, 17):
            for b in range(0, 256, 17):
                hex_value = f"#{r:02x}{g:02x}{b:02x}"
                _, chroma, hue = palette.srgb_to_oklch(hex_value)
                if chroma < palette.CHROMA_FLOOR:
                    continue
                family = palette.nearest_tint(hex_value).rsplit("-", 1)[0]
                best = min(palette.hue_distance(hue, a) for a in angles.values())
                got = palette.hue_distance(hue, angles[family])
                assert got == pytest.approx(best, abs=1e-9), (hex_value, family)
                worst = max(worst, got)
    assert worst <= 9.0


def test_nearest_tint_distinguishes_far_apart_colours():
    assert palette.nearest_tint("#c1121f") != palette.nearest_tint("#2d6a4f")


def test_nearest_tint_handles_malformed_input():
    assert palette.nearest_tint("") == palette.DEFAULT_TINT
    assert palette.nearest_tint("not-a-colour") == palette.DEFAULT_TINT
    assert palette.nearest_tint("#fff") == palette.DEFAULT_TINT  # short form unsupported
    assert palette.nearest_tint("#gggggg") == palette.DEFAULT_TINT  # not hex digits
    assert palette.nearest_tint(None) == palette.DEFAULT_TINT


def test_tint_choices_shape():
    assert len(palette.TINT_CHOICES) == 42
    # the neutral heads the list: it is the default, so it should be the
    # first thing an admin sees rather than buried between magenta and pink
    assert palette.TINT_CHOICES[0][0] == palette.DEFAULT_TINT
    keys = [k for k, _ in palette.TINT_CHOICES]
    assert keys == list(palette.TINTS)
    for key, label in palette.TINT_CHOICES:
        assert label and label != key  # human-readable, e.g. "Teal — soft"
