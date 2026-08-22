from datetime import date, timedelta

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


def test_swap_view_chain(client, admin_client, admin_user):
    # swap_new lists only day__gte=today entries, so this scenario (mirrors
    # `scenario` above) must use dates relative to the real clock rather than
    # the fixed MON/TUE constants, which recede into the past as time passes.
    duty = make_session_type("Duty", fairness_tracked=True)
    routine = make_session_type("Routine")
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    today = date.today()
    day1, day2 = today + timedelta(days=1), today + timedelta(days=2)
    entries_svc.assign_full_day(None, a, day1, duty, published=True)
    make_entry(a, day=day2, part="AM", session_type=routine)
    make_entry(b, day=day1, part="AM", session_type=routine)
    make_entry(b, day=day1, part="PM", session_type=routine)
    entries_svc.assign(None, b, day2, "AM", duty, published=True)

    ua = User.objects.create_user(email="alice@example.com", password="pw")
    ub = User.objects.create_user(email="beth4@example.com", password="pw")
    a.user = ua
    a.save()
    b.user = ub
    b.save()
    my_entry = RotaEntry.objects.get(clinician=a, day=day1, part="AM")
    their_entry = RotaEntry.objects.get(clinician=b, day=day2, part="AM")
    client.force_login(ua)
    resp = client.post("/me/swap/new/", {
        "my_entry_id": my_entry.id, "their_entry_id": their_entry.id,
        "message": "please"})
    assert resp.status_code == 302
    req = SwapRequest.objects.get()
    client.post(f"/me/swap/{req.pk}/accept/")  # proposer, not colleague
    req.refresh_from_db()
    assert req.status == SwapRequest.Status.PROPOSED
    client.force_login(ub)
    client.post(f"/me/swap/{req.pk}/accept/")
    req.refresh_from_db()
    assert req.status == SwapRequest.Status.ACCEPTED
    admin_client.post(f"/requests/swap/{req.pk}/approve/")
    req.refresh_from_db()
    assert req.status == SwapRequest.Status.APPROVED
    assert RotaEntry.objects.get(clinician=b, day=day1, part="AM").session_type == duty


def test_admin_decline_after_decision_404s(scenario, admin_client, admin_user):
    a, b, duty, routine = scenario
    req = _swap(a, b)
    ub = User.objects.create_user(email="beth5@example.com", password="pw")
    b.user = ub
    b.save()
    swaps_svc.accept(req, ub)
    swaps_svc.approve(admin_user, req)
    assert admin_client.post(f"/requests/swap/{req.pk}/decline/").status_code == 404
