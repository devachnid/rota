"""The assisted fill form.

The checkbox defaulted off and did not say what "the default session type"
was. Worse, when none is configured it does nothing at all, silently — which
gets more misleading now that it defaults on.
"""

import pytest

from rota.models import PracticeSettings
from tests.factories import make_session_type


@pytest.mark.django_db
def test_the_checkbox_is_ticked_and_names_the_type(admin_client):
    settings = PracticeSettings.load()
    settings.default_fill_session_type = make_session_type("Routine", code="ROUT")
    settings.save()

    html = admin_client.get("/rota/fill/").content.decode()
    assert "Routine" in html
    assert "checked" in html
    assert "disabled" not in html


@pytest.mark.django_db
def test_with_no_default_type_the_box_is_disabled_and_explains_itself(admin_client):
    settings = PracticeSettings.load()
    settings.default_fill_session_type = None
    settings.save()

    html = admin_client.get("/rota/fill/").content.decode()
    assert "disabled" in html
    assert "practice settings" in html.lower(), (
        "the explanation should say where to fix it"
    )
    assert "checked" not in html, "a disabled box must not look ticked"
