from datetime import timedelta

import pytest

from rota.models import LocumRequirement, RotaEntry
from rota.services import locums
from tests.factories import MON, make_clinician, make_group, make_session_type

pytestmark = pytest.mark.django_db


def test_create_and_advance_requirement(admin_user):
    st = make_session_type("Routine")
    req = locums.save_requirement(
        admin_user, day=MON, part="AM", session_type=st,
        status=LocumRequirement.Status.POSSIBLE,
    )
    req = locums.save_requirement(
        admin_user, pk=req.pk, day=MON, part="AM", session_type=st,
        status=LocumRequirement.Status.ADVERTISED, details="Agency emailed",
    )
    assert req.status == LocumRequirement.Status.ADVERTISED


def test_booking_requires_locum_clinician(admin_user):
    st = make_session_type("Routine")
    non_locum = make_clinician()
    with pytest.raises(ValueError):
        locums.save_requirement(
            admin_user, day=MON, part="AM", session_type=st,
            status=LocumRequirement.Status.BOOKED, clinician=non_locum,
        )


def test_booking_creates_published_entry(admin_user):
    st = make_session_type("Routine")
    locum_group = make_group("Locum", is_locum_group=True, display_order=99)
    locum = make_clinician("Larry Locum", group=locum_group)
    req = locums.save_requirement(
        admin_user, day=MON, part="AM", session_type=st,
        status=LocumRequirement.Status.BOOKED, clinician=locum, details="£700",
    )
    entry = RotaEntry.objects.get()
    assert req.rota_entry == entry and entry.is_published
    assert entry.clinician == locum and entry.session_type == st


def _book(admin_user):
    st = make_session_type("Routine")
    locum_group = make_group("Locum", is_locum_group=True, display_order=99)
    locum = make_clinician("Larry Locum", group=locum_group)
    req = locums.save_requirement(
        admin_user, day=MON, part="AM", session_type=st,
        status=LocumRequirement.Status.BOOKED, clinician=locum, details="£700",
    )
    return st, locum, req


def test_unbooking_is_rejected(admin_user):
    st, locum, req = _book(admin_user)
    with pytest.raises(ValueError):
        locums.save_requirement(
            admin_user, pk=req.pk, day=MON, part="AM", session_type=st,
            status=LocumRequirement.Status.ADVERTISED,
        )


def test_rebooking_different_locum_rejected(admin_user):
    st, locum, req = _book(admin_user)
    locum2 = make_clinician("Lucy Locum", group=locum.group)
    with pytest.raises(ValueError):
        locums.save_requirement(
            admin_user, pk=req.pk, day=MON, part="AM", session_type=st,
            status=LocumRequirement.Status.BOOKED, clinician=locum2,
        )
    assert RotaEntry.objects.count() == 1


def test_updating_details_of_booked_requirement_allowed(admin_user):
    st, locum, req = _book(admin_user)
    req = locums.save_requirement(
        admin_user, pk=req.pk, day=MON, part="AM", session_type=st,
        status=LocumRequirement.Status.BOOKED, details="£750 agreed",
    )
    assert req.details == "£750 agreed"
    assert req.clinician == locum and RotaEntry.objects.count() == 1


def test_moving_booked_requirement_rejected(admin_user):
    st, locum, req = _book(admin_user)
    other = make_session_type("Duty", fairness_tracked=True)
    with pytest.raises(ValueError):
        locums.save_requirement(
            admin_user, pk=req.pk, day=MON, part="AM", session_type=other,
            status=LocumRequirement.Status.BOOKED,
        )
    with pytest.raises(ValueError):
        locums.save_requirement(
            admin_user, pk=req.pk, day=MON, part="PM", session_type=st,
            status=LocumRequirement.Status.BOOKED,
        )


def test_orphaned_booking_can_step_back(admin_user):
    from rota.services import entries as entries_svc
    st, locum, req = _book(admin_user)
    entries_svc.clear(admin_user, locum, MON, "AM")
    req.refresh_from_db()
    assert req.rota_entry is None
    req = locums.save_requirement(
        admin_user, pk=req.pk, day=MON, part="AM", session_type=st,
        status=LocumRequirement.Status.ADVERTISED,
    )
    assert req.status == LocumRequirement.Status.ADVERTISED


def test_orphaned_booking_can_be_rebooked_directly(admin_user):
    from rota.services import entries as entries_svc
    st, locum, req = _book(admin_user)
    entries_svc.clear(admin_user, locum, MON, "AM")
    req.refresh_from_db()
    assert req.status == LocumRequirement.Status.BOOKED and req.rota_entry is None

    req = locums.save_requirement(
        admin_user, pk=req.pk, day=MON, part="AM", session_type=st,
        status=LocumRequirement.Status.BOOKED, clinician=locum, details="£700",
    )
    assert req.status == LocumRequirement.Status.BOOKED
    assert req.rota_entry is not None
    entry = RotaEntry.objects.get()
    assert req.rota_entry == entry
    assert entry.clinician == locum and entry.session_type == st and entry.is_published


def test_moving_booked_requirement_day_rejected(admin_user):
    st, locum, req = _book(admin_user)
    with pytest.raises(ValueError):
        locums.save_requirement(
            admin_user, pk=req.pk, day=MON + timedelta(days=1), part="AM",
            session_type=st, status=LocumRequirement.Status.BOOKED,
        )


def test_the_statuses_run_possible_approved_advertised_booked():
    S = LocumRequirement.Status
    assert [s.value for s in S] == ["POSSIBLE", "APPROVED", "ADVERTISED", "BOOKED"]
    assert S.APPROVED.label == "Need approved"


def test_covering_is_an_optional_clinician_that_survives_deletion():
    field = LocumRequirement._meta.get_field("covering")
    assert field.null and field.blank
    assert field.remote_field.model.__name__ == "Clinician"
    from django.db import models
    assert field.remote_field.on_delete is models.SET_NULL
