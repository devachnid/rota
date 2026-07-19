import pytest

from rota.models import DayNote, LocumRequirement, RotaEntry
from tests.factories import (MON, make_clinician, make_entry, make_group,
                             make_session_type)
from rota.services import locums as locums_svc

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


def test_malformed_post_returns_400_not_500(admin_client):
    c = make_clinician()
    st = make_session_type()
    resp = admin_client.post("/rota/assign/", {
        "clinician_id": c.id, "day": "not-a-date", "part": "AM",
        "session_type_id": st.id})
    assert resp.status_code == 400
    assert admin_client.post("/rota/assign/", {}).status_code == 400
    assert admin_client.post("/rota/clear/", {}).status_code == 400
    assert admin_client.post("/rota/publish/", {"start": "junk", "end": "junk"}).status_code == 400


def test_locum_error_rerender_preserves_pk(admin_client, admin_user):
    st = make_session_type()
    locum_group = make_group("Locum", is_locum_group=True, display_order=99)
    locum = make_clinician("Larry Locum", group=locum_group)
    req = locums_svc.save_requirement(
        admin_user, day=MON, part="AM", session_type=st,
        status=LocumRequirement.Status.BOOKED, clinician=locum)
    resp = admin_client.post("/rota/locum/save/", {
        "pk": req.pk, "day": MON.isoformat(), "part": "AM",
        "session_type_id": st.id, "status": "ADVERTISED"})
    assert resp.status_code == 200
    assert b"Already booked" in resp.content
    assert f'value="{req.pk}"'.encode() in resp.content
    assert LocumRequirement.objects.count() == 1
