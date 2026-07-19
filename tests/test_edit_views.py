import pytest

from rota.models import DayNote, LocumRequirement, RotaEntry
from tests.factories import (MON, make_clinician, make_entry, make_group,
                             make_session_type)

pytestmark = pytest.mark.django_db


def _assign_data(c, st, **kw):
    return {"clinician_id": c.id, "day": MON.isoformat(), "part": "AM",
            "session_type_id": st.id, "note": "", **kw}


def test_assign_requires_admin(gp_client):
    c = make_clinician()
    st = make_session_type()
    assert gp_client.post("/rota/assign/", _assign_data(c, st)).status_code == 403


def test_assign_creates_draft_entry(admin_client):
    c = make_clinician()
    st = make_session_type()
    resp = admin_client.post("/rota/assign/", _assign_data(c, st))
    assert resp.status_code == 204 and resp.headers["HX-Refresh"] == "true"
    e = RotaEntry.objects.get()
    assert e.manually_set and not e.is_published


def test_assign_full_day_makes_pair(admin_client):
    c = make_clinician()
    duty = make_session_type("Duty", fairness_tracked=True)
    admin_client.post("/rota/assign/", _assign_data(c, duty, full_day="1"))
    assert RotaEntry.objects.count() == 2
    groups = set(RotaEntry.objects.values_list("allocation_group", flat=True))
    assert len(groups) == 1 and None not in groups


def test_ineligible_warns_then_confirm_overrides(admin_client):
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    st = make_session_type("Vasectomy")
    st.allowed_clinicians.add(a)
    resp = admin_client.post("/rota/assign/", _assign_data(b, st))
    assert resp.status_code == 200 and b"not usually eligible" in resp.content
    assert not RotaEntry.objects.exists()
    admin_client.post("/rota/assign/", _assign_data(b, st, confirm="1"))
    assert RotaEntry.objects.count() == 1


def test_clear_endpoint(admin_client):
    c = make_clinician()
    make_entry(c)
    resp = admin_client.post("/rota/clear/", {
        "clinician_id": c.id, "day": MON.isoformat(), "part": "AM"})
    assert resp.status_code == 204 and not RotaEntry.objects.exists()


def test_publish_endpoint(admin_client):
    c = make_clinician()
    make_entry(c, is_published=False)
    admin_client.post("/rota/publish/", {"start": MON.isoformat(),
                                         "end": MON.isoformat()})
    assert RotaEntry.objects.get().is_published


def test_daynote_save_and_delete(admin_client):
    admin_client.post("/rota/daynote/save/", {"day": MON.isoformat(),
                                              "text": "CQC visit"})
    assert DayNote.objects.get(day=MON).text == "CQC visit"
    admin_client.post("/rota/daynote/save/", {"day": MON.isoformat(), "text": ""})
    assert not DayNote.objects.exists()


def test_locum_save_creates_requirement(admin_client):
    st = make_session_type()
    admin_client.post("/rota/locum/save/", {
        "day": MON.isoformat(), "part": "AM", "session_type_id": st.id,
        "status": "ADVERTISED", "details": "agency emailed"})
    assert LocumRequirement.objects.get().status == "ADVERTISED"
