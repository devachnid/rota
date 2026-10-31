"""The clinician admin after the FindMyShift staff link went: no link field, and the login email is how Shift Central's leave is matched."""

import pytest

from tests.factories import make_clinician

pytestmark = pytest.mark.django_db


def test_the_change_form_has_no_staff_link_and_explains_the_email_match(staff_client):
    c = make_clinician("Ann Able")
    html = staff_client.get(f"/admin/rota/clinician/{c.pk}/change/").content.decode()
    assert "Shift Central matches this person's leave by this login's email." in html
    assert "staff_id" not in html and "FindMyShift" not in html


def test_the_list_has_no_link_column_or_filter(staff_client):
    make_clinician("Ann Able")
    resp = staff_client.get("/admin/rota/clinician/")
    html = resp.content.decode()
    assert resp.status_code == 200 and "Ann Able" in html
    assert "FindMyShift" not in html and "not linked" not in html.lower()
