import pytest

from rota.models import DayNote, LocumRequirement, PracticeSettings, RotaEntry
from tests.factories import (MON, make_clinician, make_entry, make_group,
                             make_session_type, make_site, make_trainee)
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
    admin_client.post("/rota/assign/", _assign_data(c, duty, part="DAY"))
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


def test_ineligible_warning_preserves_typed_note_and_site(admin_client):
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    st = make_session_type("Vasectomy")
    st.allowed_clinicians.add(a)
    site = make_site("Branch Surgery")
    resp = admin_client.post("/rota/assign/", _assign_data(
        b, st, note="please double-check", site_id=str(site.id)))
    assert resp.status_code == 200 and b"not usually eligible" in resp.content
    assert not RotaEntry.objects.exists()
    assert b"please double-check" in resp.content
    assert f'value="{site.id}" selected'.encode() in resp.content


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


def test_invalid_part_returns_400_and_creates_nothing(admin_client):
    c = make_clinician()
    st = make_session_type()

    resp = admin_client.post("/rota/assign/", _assign_data(c, st, part="ZZ"))
    assert resp.status_code == 400
    assert not RotaEntry.objects.exists()

    make_entry(c)
    resp = admin_client.post("/rota/clear/", {
        "clinician_id": c.id, "day": MON.isoformat(), "part": "ZZ"})
    assert resp.status_code == 400
    assert RotaEntry.objects.count() == 1

    resp = admin_client.post("/rota/locum/save/", {
        "day": MON.isoformat(), "part": "ZZ", "session_type_id": st.id,
        "status": "ADVERTISED"})
    assert resp.status_code == 400
    assert not LocumRequirement.objects.exists()


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


def test_the_locum_form_lists_the_four_statuses_in_order(admin_client):
    make_session_type()
    html = admin_client.get(f"/rota/locum/new/?day={MON.isoformat()}&part=AM").content.decode()
    labels = ["Possibly needed", "Need approved", "Advertised", "Booked"]
    positions = [html.index(label) for label in labels]
    assert positions == sorted(positions), labels


def test_locum_save_records_covering(admin_client):
    st = make_session_type()
    covered = make_clinician("Cara Covered")
    admin_client.post("/rota/locum/save/", {
        "day": MON.isoformat(), "part": "AM", "session_type_id": st.id,
        "status": "APPROVED", "covering_id": covered.id})
    assert LocumRequirement.objects.get().covering == covered


def test_an_inactive_covering_id_is_not_stored(admin_client):
    st = make_session_type()
    inactive = make_clinician("Ivy Inactive", active=False)
    admin_client.post("/rota/locum/save/", {
        "day": MON.isoformat(), "part": "AM", "session_type_id": st.id,
        "status": "ADVERTISED", "covering_id": inactive.id})
    assert LocumRequirement.objects.get().covering is None


def test_the_covering_dropdown_offers_no_locums(admin_client):
    make_session_type()
    make_clinician("Cara Covered")
    locum_group = make_group("Locum", is_locum_group=True, display_order=99)
    make_clinician("Larry Locum", group=locum_group)
    html = admin_client.get(f"/rota/locum/new/?day={MON.isoformat()}&part=AM").content.decode()
    covering = html[html.index('id="id_covering_id"'):html.index("</select>", html.index('id="id_covering_id"'))]
    assert "Cara Covered" in covering
    assert "Larry Locum" not in covering


# --------------------------------------------------------------------------
# the Session dropdown: grouped Clinical / Non-clinical / Absence, opening
# on the practice's default fill type for an empty cell
# --------------------------------------------------------------------------

def _three_types():
    routine = make_session_type("Routine")
    meeting = make_session_type("Meeting", code="MTG", category="NON_CLINICAL")
    leave = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    return routine, meeting, leave


def test_the_session_dropdown_is_grouped_clinical_first(admin_client):
    routine, meeting, leave = _three_types()
    c = make_clinician()
    html = admin_client.get(f"/rota/cell/{c.id}/{MON.isoformat()}/AM/").content.decode()
    clinical = html.index('<optgroup label="Clinical">')
    non_clinical = html.index('<optgroup label="Non-clinical">')
    absence = html.index('<optgroup label="Absence">')
    assert clinical < non_clinical < absence
    assert clinical < html.index(f'value="{routine.id}"') < non_clinical
    assert non_clinical < html.index(f'value="{meeting.id}"') < absence
    assert absence < html.index(f'value="{leave.id}"')


def test_an_empty_cell_opens_on_the_default_fill_type_and_a_held_cell_on_its_own(admin_client):
    routine, meeting, leave = _three_types()
    PracticeSettings.objects.update_or_create(pk=1, defaults={"default_fill_session_type": routine})
    c = make_clinician()
    html = admin_client.get(f"/rota/cell/{c.id}/{MON.isoformat()}/AM/").content.decode()
    assert f'value="{routine.id}" selected' in html
    make_entry(c, day=MON, part="PM", session_type=meeting)
    html = admin_client.get(f"/rota/cell/{c.id}/{MON.isoformat()}/PM/").content.decode()
    assert f'value="{meeting.id}" selected' in html
    assert f'value="{routine.id}" selected' not in html


def test_without_a_default_fill_type_nothing_is_preselected(admin_client):
    routine, meeting, leave = _three_types()
    c = make_clinician()
    html = admin_client.get(f"/rota/cell/{c.id}/{MON.isoformat()}/AM/").content.decode()
    assert " selected" not in html.split('name="site_id"')[0]


def test_the_locum_form_groups_its_session_types_the_same_way(admin_client):
    _three_types()
    html = admin_client.get(f"/rota/locum/new/?day={MON.isoformat()}&part=AM").content.decode()
    assert html.index('<optgroup label="Clinical">') < html.index('<optgroup label="Absence">')


# --------------------------------------------------------------------------
# a mentoring session added by hand is a pair, like the one assisted fill
# makes: a "With" partner, both rotas written and linked
# --------------------------------------------------------------------------

def _mentoring():
    ment = make_session_type("Mentoring", code="Mentor", category="NON_CLINICAL")
    PracticeSettings.objects.update_or_create(pk=1, defaults={"mentoring_session_type": ment})
    return ment


def _pair():
    trainer = make_clinician("Tina Trainer", is_trainer=True)
    trainee = make_clinician("Terry Trainee")
    make_trainee(trainee, trainer=trainer)
    return trainer, trainee


def test_the_with_field_is_there_for_mentoring_and_preselects_the_natural_partner(admin_client):
    _mentoring()
    trainer, trainee = _pair()
    html = admin_client.get(f"/rota/cell/{trainee.id}/{MON.isoformat()}/AM/").content.decode()
    assert 'id="partner-field" hidden' in html  # nothing selected yet, so hidden
    assert "getElementById('partner-field').hidden" in html
    assert f'value="{trainer.id}" selected' in html
    html = admin_client.get(f"/rota/cell/{trainer.id}/{MON.isoformat()}/AM/").content.decode()
    assert f'value="{trainee.id}" selected' in html  # their only trainee


def test_no_with_field_when_the_practice_has_no_mentoring_type(admin_client):
    c = make_clinician()
    html = admin_client.get(f"/rota/cell/{c.id}/{MON.isoformat()}/AM/").content.decode()
    assert "partner-field" not in html and "partner_id" not in html


def test_a_mentoring_session_with_a_partner_is_written_to_both_rotas_as_a_pair(admin_client):
    ment = _mentoring()
    trainer, trainee = _pair()
    resp = admin_client.post("/rota/assign/", _assign_data(
        trainee, ment, partner_id=trainer.id, note="First week"))
    assert resp.status_code == 204
    mine = RotaEntry.objects.get(clinician=trainee)
    theirs = RotaEntry.objects.get(clinician=trainer)
    assert mine.companion_group is not None
    assert mine.companion_group == theirs.companion_group
    assert theirs.session_type == ment and theirs.note == "First week" and theirs.manually_set
    html = admin_client.get(f"/rota/?week={MON.isoformat()}").content.decode()
    assert "with Tina Trainer" in html and "with Terry Trainee" in html
    # Re-opening either cell shows the pair, field visible.
    html = admin_client.get(f"/rota/cell/{trainer.id}/{MON.isoformat()}/AM/").content.decode()
    assert 'id="partner-field">' in html
    assert f'value="{trainee.id}" selected' in html


def test_a_partner_holding_something_else_is_asked_about_then_replaced(admin_client):
    ment = _mentoring()
    routine = make_session_type("Routine")
    trainer, trainee = _pair()
    make_entry(trainer, day=MON, part="AM", session_type=routine)
    resp = admin_client.post("/rota/assign/", _assign_data(trainee, ment, partner_id=trainer.id))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert ("Tina Trainer already has Routine on Mon 20 Jul AM. Save again to "
            "replace it with Mentoring.") in html
    assert 'name="replace" value="1"' in html
    assert f'value="{trainer.id}" selected' in html
    assert not RotaEntry.objects.filter(clinician=trainee).exists()
    admin_client.post("/rota/assign/", _assign_data(trainee, ment, partner_id=trainer.id, replace="1"))
    assert RotaEntry.objects.count() == 2
    assert RotaEntry.objects.get(clinician=trainer).session_type == ment


def test_a_partner_already_on_mentoring_is_linked_without_a_question(admin_client):
    ment = _mentoring()
    trainer, trainee = _pair()
    make_entry(trainer, day=MON, part="AM", session_type=ment)
    resp = admin_client.post("/rota/assign/", _assign_data(trainee, ment, partner_id=trainer.id))
    assert resp.status_code == 204
    groups = set(RotaEntry.objects.values_list("companion_group", flat=True))
    assert len(groups) == 1 and None not in groups and RotaEntry.objects.count() == 2


def test_a_partner_is_ignored_for_any_other_session_type(admin_client):
    _mentoring()
    routine = make_session_type("Routine")
    trainer, trainee = _pair()
    admin_client.post("/rota/assign/", _assign_data(trainee, routine, partner_id=trainer.id))
    assert RotaEntry.objects.count() == 1
    assert not RotaEntry.objects.filter(clinician=trainer).exists()


def test_full_day_mentoring_pairs_both_halves(admin_client):
    ment = _mentoring()
    trainer, trainee = _pair()
    admin_client.post("/rota/assign/", _assign_data(trainee, ment, partner_id=trainer.id, part="DAY"))
    assert RotaEntry.objects.count() == 4
    am = {e.clinician_id: e for e in RotaEntry.objects.filter(part="AM")}
    pm = {e.clinician_id: e for e in RotaEntry.objects.filter(part="PM")}
    assert am[trainee.id].companion_group == am[trainer.id].companion_group
    assert pm[trainee.id].companion_group == pm[trainer.id].companion_group
    assert am[trainee.id].companion_group != pm[trainee.id].companion_group


def test_choosing_yourself_as_the_partner_is_refused(admin_client):
    ment = _mentoring()
    trainer, trainee = _pair()
    resp = admin_client.post("/rota/assign/", _assign_data(trainee, ment, partner_id=trainee.id))
    assert resp.status_code == 400 and not RotaEntry.objects.exists()


def test_the_eligibility_question_keeps_the_partner_and_still_asks_about_a_held_slot(admin_client):
    ment = _mentoring()
    ment.allowed_clinicians.add(make_clinician("Someone Else"))
    routine = make_session_type("Routine")
    trainer, trainee = _pair()
    make_entry(trainer, day=MON, part="AM", session_type=routine)
    html = admin_client.post("/rota/assign/", _assign_data(trainee, ment, partner_id=trainer.id)).content.decode()
    assert "not usually eligible" in html and f'value="{trainer.id}" selected' in html
    html = admin_client.post("/rota/assign/", _assign_data(
        trainee, ment, partner_id=trainer.id, confirm="1")).content.decode()
    assert "already has Routine" in html and 'name="confirm" value="1"' in html
    admin_client.post("/rota/assign/", _assign_data(
        trainee, ment, partner_id=trainer.id, confirm="1", replace="1"))
    assert RotaEntry.objects.count() == 2
