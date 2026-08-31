from datetime import timedelta

import pytest

from rota.models import PatternSlot
from tests.factories import MON, make_clinician, make_pattern

pytestmark = pytest.mark.django_db

URL = "/admin/rota/patternslot/bulk/"


def test_requires_staff(gp_client):
    c = make_clinician()
    resp = gp_client.get(URL, {"clinician_id": c.id})
    assert resp.status_code == 302


def test_anonymous_redirected(client):
    resp = client.get(URL)
    assert resp.status_code == 302


def test_get_without_clinician_shows_select(staff_client):
    c = make_clinician("Alice Adams")
    resp = staff_client.get(URL)
    assert resp.status_code == 200
    assert b"Alice Adams" in resp.content
    assert b'name="d0_AM"' not in resp.content  # no grid until a clinician is chosen


def test_get_prefills_existing_pattern(staff_client):
    c = make_clinician()
    make_pattern(c, weekdays=(0, 1, 2, 3, 4), parts=("AM", "PM"),
                 effective_from=MON - timedelta(days=365))
    resp = staff_client.get(URL, {"clinician_id": c.id,
                                 "effective_from": MON.isoformat()})
    html = resp.content.decode()
    assert 'name="d0_AM" checked' in html
    assert 'name="d0_PM" checked' in html
    assert 'name="d5_AM" checked' not in html  # Saturday, never worked
    assert 'name="d6_PM" checked' not in html  # Sunday


def test_post_creates_only_changed_rows_and_redirects(staff_client):
    c = make_clinician()
    make_pattern(c, weekdays=(0, 1, 2, 3, 4), parts=("AM", "PM"),
                 effective_from=MON - timedelta(days=365))
    data = {"action": "save", "clinician_id": c.id,
            "effective_from": MON.isoformat()}
    for w in (0, 1, 2, 3, 4):
        for p in ("AM", "PM"):
            if (w, p) == (1, "PM"):
                continue  # dropping Tuesday PM
            data[f"d{w}_{p}"] = "on"
    data["d5_AM"] = "on"  # adding Saturday AM

    resp = staff_client.post(URL, data)

    assert resp.status_code == 302
    at_mon = PatternSlot.objects.filter(clinician=c, effective_from=MON)
    assert at_mon.count() == 2
    assert at_mon.get(weekday=1, part="PM").works is False
    assert at_mon.get(weekday=5, part="AM").works is True


def test_post_resave_updates_in_place(staff_client):
    c = make_clinician()
    data = {"action": "save", "clinician_id": c.id,
            "effective_from": MON.isoformat(), "d0_AM": "on"}
    staff_client.post(URL, data)
    staff_client.post(URL, {"action": "save", "clinician_id": c.id,
                            "effective_from": MON.isoformat()})  # untick it
    rows = PatternSlot.objects.filter(clinician=c, weekday=0, part="AM")
    assert rows.count() == 1
    assert rows.get().works is False
