"""The assisted fill form.

The checkbox defaulted off and did not say what "the default session type"
was. Worse, when none is configured it does nothing at all, silently — which
gets more misleading now that it defaults on.
"""

import re
from datetime import date

import pytest

from rota.models import PracticeSettings
from rota.services.next_week import next_monday
from tests.factories import make_clinician, make_pattern, make_session_type


@pytest.mark.django_db
def test_the_checkbox_is_ticked_and_names_the_type(admin_client):
    settings = PracticeSettings.load()
    settings.default_fill_session_type = make_session_type("Routine", code="ROUT")
    settings.save()

    html = admin_client.get("/rota/fill/").content.decode()
    assert "Routine" in html
    # Scoped to the checkbox: the Delete-drafts card below it has default-checked radios.
    tag = re.search(r'<input[^>]*name="fill_default"[^>]*>', html).group(0)
    assert "checked" in tag
    assert "disabled" not in tag


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
    # Scoped to the checkbox: the Delete-drafts card below it has default-checked radios.
    tag = re.search(r'<input[^>]*name="fill_default"[^>]*>', html).group(0)
    assert "disabled" in tag
    assert "checked" not in tag


@pytest.mark.django_db
def test_the_start_date_is_the_first_week_under_half_filled(admin_client):
    PracticeSettings.load()
    make_pattern(make_clinician("Alice Adams"))
    html = admin_client.get("/rota/fill/").content.decode()
    expected = next_monday(date.today())
    assert f'name="start" id="id_fill_start" value="{expected}"' in html
    assert "Suggested from" in html
    assert "the first week under half filled (0 of 10 sessions)" in html


@pytest.mark.django_db
def test_with_nothing_to_suggest_the_form_says_so(admin_client):
    """No clinician works anything, so no week has a working session and
    none can be under half: the default is next Monday and the line
    explains."""
    PracticeSettings.load()
    html = admin_client.get("/rota/fill/").content.decode()
    assert "No week to" in html and "defaulting to next Monday" in html
    assert f'value="{next_monday(date.today())}"' in html
