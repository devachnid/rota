from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model

from rota.models import RotaEntry, SwapRequest
from rota.services import entries as entries_svc
from rota.services import swaps as swaps_svc
from tests.factories import MON, make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db
User = get_user_model()
TUE = MON + timedelta(days=1)


@pytest.fixture
def scenario(db):
    """Alice has Duty Mon (full day) + Routine Tue; Beth mirrors."""
    duty = make_session_type("Duty", fairness_tracked=True)
    routine = make_session_type("Routine")
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    entries_svc.assign_full_day(None, a, MON, duty, published=True)
    make_entry(a, day=TUE, part="AM", session_type=routine)
    make_entry(b, day=MON, part="AM", session_type=routine)
    make_entry(b, day=MON, part="PM", session_type=routine)
    entries_svc.assign(None, b, TUE, "AM", duty, published=True)
    return a, b, duty, routine


def _swap(a, b):
    return SwapRequest.objects.create(
        proposer=a, proposer_day=MON, proposer_part="AM",
        colleague=b, colleague_day=TUE, colleague_part="AM")


def test_duty_pair_expands_slots(scenario):
    a, b, *_ = scenario
    req = _swap(a, b)
    assert set(swaps_svc.involved_slots(req)) == {(MON, "AM"), (MON, "PM"),
                                                  (TUE, "AM")}


def test_validate_catches_missing_entries(scenario):
    a, b, duty, routine = scenario
    RotaEntry.objects.filter(clinician=b, day=MON, part="PM").delete()
    req = _swap(a, b)
    problems = swaps_svc.validate(req)
    assert problems and "Beth Brown" in problems[0]


def test_apply_swaps_types_and_pair_group(scenario, admin_user):
    a, b, duty, routine = scenario
    req = _swap(a, b)
    gp_user = User.objects.create_user(email="beth@example.com", password="pw")
    b.user = gp_user
    b.save()
    swaps_svc.accept(req, gp_user)
    swaps_svc.approve(admin_user, req)
    req.refresh_from_db()
    assert req.status == SwapRequest.Status.APPROVED
    # Beth now holds the linked duty day; Alice holds Beth's old sessions
    b_mon = {e.part: e for e in RotaEntry.objects.filter(clinician=b, day=MON)}
    assert b_mon["AM"].session_type == duty and b_mon["PM"].session_type == duty
    assert (b_mon["AM"].allocation_group
            and b_mon["AM"].allocation_group == b_mon["PM"].allocation_group)
    a_mon = {e.part: e for e in RotaEntry.objects.filter(clinician=a, day=MON)}
    assert a_mon["AM"].session_type == routine
    assert a_mon["AM"].allocation_group is None
    assert RotaEntry.objects.get(clinician=a, day=TUE, part="AM").session_type == duty


def test_accept_requires_colleague(scenario):
    a, b, *_ = scenario
    req = _swap(a, b)
    stranger = User.objects.create_user(email="x@example.com", password="pw")
    with pytest.raises(PermissionError):
        swaps_svc.accept(req, stranger)


def test_declining_applied_swap_rejected(scenario, admin_user):
    a, b, duty, routine = scenario
    req = _swap(a, b)
    gp_user = User.objects.create_user(email="beth2@example.com", password="pw")
    b.user = gp_user
    b.save()
    swaps_svc.accept(req, gp_user)
    swaps_svc.approve(admin_user, req)
    with pytest.raises(ValueError):
        swaps_svc.decline(admin_user, req)
    with pytest.raises(ValueError):
        swaps_svc.decline_by_colleague(req, gp_user)
    req.refresh_from_db()
    assert req.status == SwapRequest.Status.APPROVED
