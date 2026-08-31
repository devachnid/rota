"""Colour is the point of the field, so the admin should show it.

The dropdown listed 42 names with no colour, and the list view showed a key
like `teal-strong` — you had to know the palette by heart to use either.
"""

import pytest

from rota import palette
from tests.factories import make_session_type


@pytest.mark.django_db
def test_the_list_view_shows_a_swatch_in_the_tint_s_own_colours(staff_client):
    st = make_session_type("Duty", code="DUTY")
    st.colour = "teal-strong"
    st.save()
    html = staff_client.get("/admin/rota/sessiontype/").content.decode()
    tint = palette.TINTS["teal-strong"]
    assert tint.bg in html, "the swatch is not painted in the tint's background"
    assert tint.fg in html


@pytest.mark.django_db
def test_the_picker_renders_every_tint_as_a_choosable_swatch(staff_client):
    st = make_session_type("Duty2", code="DT2")
    html = staff_client.get(
        f"/admin/rota/sessiontype/{st.pk}/change/").content.decode()
    assert html.count('name="colour"') == len(palette.TINTS), (
        "expected one radio input per tint"
    )
    for key in ("neutral-soft", "red-strong", "azure-soft"):
        assert palette.TINTS[key].bg in html


@pytest.mark.django_db
def test_the_currently_chosen_tint_is_selected(staff_client):
    st = make_session_type("Duty3", code="DT3")
    st.colour = "amber-soft"
    st.save()
    html = staff_client.get(
        f"/admin/rota/sessiontype/{st.pk}/change/").content.decode()
    assert 'value="amber-soft" checked' in html.replace('checked=""', "checked")


def test_no_colour_is_hardcoded_in_the_widget():
    """Every colour must come from the palette, or the two drift apart."""
    import re
    from pathlib import Path
    import rota.admin_widgets as widgets

    source = Path(widgets.__file__).read_text()
    literals = re.findall(r"#[0-9a-fA-F]{3,6}\b", source)
    assert not literals, f"hardcoded colours in the widget: {literals}"
