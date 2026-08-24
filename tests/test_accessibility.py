import pytest

from rota.models import PracticeSettings
from tests.factories import MON, make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db


def test_grid_table_has_scope_and_caption(admin_client):
    PracticeSettings.load()
    c = make_clinician()
    make_entry(c, part="AM", session_type=make_session_type("Routine", code="ROUT"))
    html = admin_client.get(f"/rota/?week={MON}").content.decode()
    assert "<caption" in html
    assert 'scope="col"' in html
    assert 'scope="row"' in html


def test_pages_declare_a_language_and_viewport(client, db):
    html = client.get("/accounts/login/").content.decode()
    assert '<html lang="en">' in html
    assert 'name="viewport"' in html
