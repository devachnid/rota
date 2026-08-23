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
