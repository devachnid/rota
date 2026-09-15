"""Rows within a group follow an admin-set order, then name. Until an
admin sets one, everyone is 100 and the grid is alphabetical as before."""

import pytest

from rota.models import Clinician, PracticeSettings
from tests.factories import MON, make_clinician, make_pattern

pytestmark = pytest.mark.django_db


def test_clinicians_order_by_display_order_then_name():
    beth = make_clinician("Beth Brown", display_order=1)
    alice = make_clinician("Alice Adams")            # default 100
    cara = make_clinician("Cara Cole", display_order=1)
    assert list(Clinician.objects.all()) == [beth, cara, alice]


def test_the_grid_follows_display_order_within_a_group(admin_client):
    PracticeSettings.load()
    make_clinician("Alice Adams", initials="AA")
    make_clinician("Zed Zane", initials="ZZ", display_order=1)
    html = admin_client.get(f"/rota/?week={MON}").content.decode()
    assert html.index('title="Zed Zane"') < html.index('title="Alice Adams"')


def test_the_day_view_follows_display_order(admin_client):
    PracticeSettings.load()
    for name, order in (("Alice Adams", 100), ("Zed Zane", 1)):
        make_pattern(make_clinician(name, display_order=order))
    html = admin_client.get(f"/rota/day/{MON}/").content.decode()
    assert html.index("Zed Zane") < html.index("Alice Adams")


def test_the_admin_list_edits_the_order_inline(admin_client):
    make_clinician("Alice Adams")
    html = admin_client.get("/admin/rota/clinician/").content.decode()
    assert 'name="form-0-display_order"' in html
