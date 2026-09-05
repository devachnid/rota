from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils.html import escape

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


def test_swap_new_excludes_clinicians_with_no_login(client):
    # A swap proposed against a clinician with no linked User can never be
    # accepted (only that user can accept it) and sits at PROPOSED forever.
    # `theirs` must exclude such clinicians entirely.
    routine = make_session_type("Routine")
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")  # b: no user
    today = date.today()
    day1 = today + timedelta(days=1)
    make_entry(a, day=day1, part="AM", session_type=routine, is_published=True)
    their_entry = make_entry(b, day=day1, part="AM", session_type=routine,
                             is_published=True)

    ua = User.objects.create_user(email="alice6@example.com", password="pw")
    a.user = ua
    a.save()
    client.force_login(ua)

    resp = client.get("/me/swap/new/")
    assert b"Beth Brown" not in resp.content

    # Posting her id anyway is answered on the page, not with a 404.
    my_entry = RotaEntry.objects.get(clinician=a, day=day1, part="AM")
    resp = client.post("/me/swap/new/", {
        "my_entry_id": my_entry.id, "their_entry_id": their_entry.id})
    assert resp.status_code == 200
    assert not SwapRequest.objects.exists()


# --------------------------------------------------------------------------
# The propose-a-swap page: what it says when there is nothing to offer, and
# how it answers a bad submission. Found on staging, where the only account
# was the admin's own: the colleague list was empty and a blank submit fell
# through to a text/plain "Bad request: 'their_entry_id'".
# --------------------------------------------------------------------------

def _gp(name, email):
    """A clinician who can sign in."""
    c = make_clinician(name)
    c.user = User.objects.create_user(email=email, password="pw")
    c.save()
    return c


@pytest.fixture
def pair(client):
    """Alice and Beth both sign in and both have a published session
    tomorrow; Alice is logged in."""
    routine = make_session_type("Routine")
    a = _gp("Alice Adams", "alice.pair@example.com")
    b = _gp("Beth Brown", "beth.pair@example.com")
    day1 = date.today() + timedelta(days=1)
    mine = make_entry(a, day=day1, part="AM", session_type=routine)
    theirs = make_entry(b, day=day1, part="PM", session_type=routine)
    client.force_login(a.user)
    return a, b, mine, theirs


def test_a_blank_submission_is_answered_on_the_form(client, pair):
    resp = client.post("/me/swap/new/", {})
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Choose one of your sessions." in html
    assert escape("Choose a colleague's session.") in html
    assert "Bad request" not in html
    assert not SwapRequest.objects.exists()


def test_the_half_that_was_chosen_survives_a_failed_submission(client, pair):
    a, b, mine, theirs = pair
    html = client.post("/me/swap/new/", {"my_entry_id": mine.id,
                                          "message": "please?"}).content.decode()
    assert f'value="{mine.id}" selected' in html
    assert "please?" in html
    assert escape("Choose a colleague's session.") in html


def test_an_id_from_outside_the_lists_is_a_field_error_not_a_404(client, pair):
    a, b, mine, theirs = pair
    # Beth's session offered as mine, and a string that is not an id at all.
    for bad in (theirs.id, "abc"):
        resp = client.post("/me/swap/new/", {"my_entry_id": bad,
                                              "their_entry_id": theirs.id})
        assert resp.status_code == 200
        assert escape("That isn't one of your upcoming published sessions") in resp.content.decode()
    assert not SwapRequest.objects.exists()


def test_colleagues_sessions_are_grouped_by_colleague(client, pair):
    a, b, mine, theirs = pair
    # A second colleague whose session falls *before* Beth's: the list is by
    # colleague first, so his group comes second and holds only his session.
    c = _gp("Carl Cole", "carl.pair@example.com")
    carls = make_entry(c, day=date.today(), part="AM", session_type=theirs.session_type)
    html = client.get("/me/swap/new/").content.decode()
    beth, carl = html.index('<optgroup label="Beth Brown">'), html.index('<optgroup label="Carl Cole">')
    assert beth < html.index(f'value="{theirs.id}"') < carl < html.index(f'value="{carls.id}"')
    assert 'value="">Choose' in html
    assert "Only colleagues who can sign in are listed" in html


def test_when_no_colleague_can_sign_in_the_page_says_so(client):
    routine = make_session_type("Routine")
    a = _gp("Alice Adams", "alice.solo@example.com")
    b = make_clinician("Beth Brown")  # on the rota, no login
    day1 = date.today() + timedelta(days=1)
    make_entry(a, day=day1, part="AM", session_type=routine)
    make_entry(b, day=day1, part="PM", session_type=routine)
    client.force_login(a.user)
    html = client.get("/me/swap/new/").content.decode()
    assert "None of your colleagues has a login account yet" in html
    assert "<select" not in html
    assert "Beth Brown" not in html
    assert 'href="/me/"' in html


def test_when_colleagues_have_nothing_published_the_page_says_that_instead(client):
    routine = make_session_type("Routine")
    a = _gp("Alice Adams", "alice.only@example.com")
    b = _gp("Beth Brown", "beth.only@example.com")
    day1 = date.today() + timedelta(days=1)
    make_entry(a, day=day1, part="AM", session_type=routine)
    make_entry(b, day=day1, part="PM", session_type=routine, is_published=False)
    make_entry(b, day=day1 - timedelta(days=7), part="AM", session_type=routine)
    client.force_login(a.user)
    html = client.get("/me/swap/new/").content.decode()
    assert "None of your colleagues who can sign in has a published session coming up" in html
    assert "<select" not in html


def test_when_i_have_nothing_published_the_page_says_so(client):
    routine = make_session_type("Routine")
    a = _gp("Alice Adams", "alice.none@example.com")
    b = _gp("Beth Brown", "beth.none@example.com")
    day1 = date.today() + timedelta(days=1)
    make_entry(b, day=day1, part="PM", session_type=routine)
    client.force_login(a.user)
    html = client.get("/me/swap/new/").content.decode()
    assert "You have no published sessions coming up" in html
    assert "<select" not in html


def test_the_colleague_sees_the_proposal_on_my_schedule(client, pair):
    a, b, mine, theirs = pair
    assert client.post("/me/swap/new/", {"my_entry_id": mine.id,
                                          "their_entry_id": theirs.id,
                                          "message": "School run"}).status_code == 302
    client.force_login(b.user)
    html = client.get("/me/").content.decode()
    assert "Waiting for you" in html
    assert "Alice Adams proposes swapping" in html and "School run" in html
    req = SwapRequest.objects.get()
    assert f'action="/me/swap/{req.pk}/accept/"' in html
    assert f'action="/me/swap/{req.pk}/decline/"' in html
