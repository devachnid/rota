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
    ("#db2777", "slate-strong"),  # H=  0.6 -> slate(360) +0.6 vs red(18) +17.4
    ("#c2185b", "slate-strong"),  # H=  5.6 -> slate(360) +5.6 vs red(18) +12.4
    ("#ff1493", "slate-strong"),  # H=357.0 -> slate(360) +3.1 vs pink(342) +14.9
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


@pytest.mark.parametrize("hex_value", ["#cccccc", "#888888", "#ffffff", "#000000"])
def test_nearest_tint_sends_neutrals_to_the_default(hex_value):
    """A grey has no hue to preserve, so inventing one is a lie.

    Their measured chroma is ~1e-10 and their reported hue is pure
    floating-point residue: #cccccc, #888888 and #ffffff all come out at
    H~89.9 for no reason other than the LMS matrix rows summing to 1.0 to ten
    decimal places, and #000000 lands on exactly 0. The old code duly filed
    them under emerald, emerald, purple and green respectively.
    """
    assert palette.nearest_tint(hex_value) == palette.DEFAULT_TINT


def test_neutrals_really_do_report_a_meaningless_hue():
    """Guards the premise of the chroma floor, so it cannot rot silently."""
    for grey in ("#cccccc", "#888888", "#ffffff"):
        L, C, H = palette.srgb_to_oklch(grey)
        assert C < 1e-6, (grey, C)
        assert H == pytest.approx(89.87, abs=0.1), (grey, H)  # noise, not yellow


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
    assert len(palette.TINT_CHOICES) == 40
    keys = [k for k, _ in palette.TINT_CHOICES]
    assert keys == list(palette.TINTS)
    for key, label in palette.TINT_CHOICES:
        assert label and label != key  # human-readable, e.g. "Teal — soft"
