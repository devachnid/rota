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


def test_legacy_hex_maps_to_a_sensible_tint():
    # The mapping function the data migration uses, exercised directly:
    # a red maps to a red-ish tint, a green to a green-ish one.
    red = palette.nearest_tint("#c1121f")
    green = palette.nearest_tint("#2d6a4f")
    assert red != green
    assert red in palette.TINTS and green in palette.TINTS

    # Check that hue families match expectations
    red_hue = red.rsplit("-", 1)[0]
    green_hue = green.rsplit("-", 1)[0]
    # Red input should map to a warm hue (red, vermilion, orange, amber, yellow)
    assert red_hue in {"red", "vermilion", "orange", "amber", "yellow"}
    # Green input should map to a cool hue (green, emerald, jade, teal, cyan)
    assert green_hue in {"green", "emerald", "jade", "teal", "cyan"}


def test_migration_round_trips_awkward_values():
    # Verify that the forward and reverse migration functions (applied in sequence)
    # leave awkward values unchanged: blank strings, hex without #, malformed values.
    # Import the migration functions directly.
    from django.apps import apps as django_apps
    migration = __import__("rota.migrations.0015_map_legacy_colours", fromlist=["to_tints", "back_to_hex"])
    to_tints = migration.to_tints
    back_to_hex = migration.back_to_hex

    # Create test cases: normal hex, hex without #, empty string, malformed
    # All should start as pre-migration values (hex or invalid strings)
    # Note: pre-migration colour field was max_length=7, so values are constrained to that
    st1 = SessionType.objects.create(name="Normal", code="NRM", category="CLINICAL", colour="#ff0000")
    st2 = SessionType.objects.create(name="NoHash", code="NOH", category="CLINICAL", colour="8ecae6")
    st3 = SessionType.objects.create(name="Empty", code="EMP", category="CLINICAL", colour="")
    st4 = SessionType.objects.create(name="Malformed", code="MAL", category="CLINICAL", colour="badval")

    # Record original values
    originals = {
        st1.pk: "#ff0000",
        st2.pk: "8ecae6",
        st3.pk: "",
        st4.pk: "badval",
    }

    # Apply forward migration
    to_tints(django_apps, None)

    # Apply reverse migration
    back_to_hex(django_apps, None)

    # Check that all rows restore to their originals
    for st in [st1, st2, st3, st4]:
        st.refresh_from_db()
        assert st.colour == originals[st.pk], \
            f"Row {st.pk} did not round-trip: expected {originals[st.pk]!r}, got {st.colour!r}"
