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
