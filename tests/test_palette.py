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


def test_nearest_tint_preserves_hue_family():
    # The v1 default is a light blue; it must land in the blue region of the
    # wheel, never on a green or a red. Which TONE it picks is not the point.
    key = palette.nearest_tint("#8ecae6")
    hue = key.rsplit("-", 1)[0]
    assert hue in {"teal", "cyan", "sky", "azure", "blue"}, key


def test_nearest_tint_is_stable_for_near_identical_colours():
    assert palette.nearest_tint("#8ecae6") == palette.nearest_tint("#8fcbe7")


@pytest.mark.parametrize("hex_value,expected_key", [
    ("#cdb4db", "violet-strong"),   # pale lavender — the original bug case
    ("#bde0fe", "indigo-strong"),   # pale blue
    ("#a0c4ff", "blue-strong"),     # pale periwinkle
    ("#ffadad", "vermilion-strong"), # pale red
    ("#caffbf", "emerald-soft"),    # pale green
])
def test_nearest_tint_maps_pastels_exactly(hex_value, expected_key):
    """Pastels are what a colour picker produces, so they are the input class
    the migration will actually meet. Exact keys, not hue-family sets: the
    palette is deterministic, and an over-broad set would let the hue-blind
    bug this replaced pass unnoticed. If this fails, the palette moved —
    re-verify the mapping rather than widening the assertion.
    """
    assert palette.nearest_tint(hex_value) == expected_key


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
