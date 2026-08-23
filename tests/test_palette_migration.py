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
