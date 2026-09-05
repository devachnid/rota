import uuid
from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils.html import escape

from rota.models import RotaEntry, RotaEntryLog, SwapRequest
from rota.services import entries as entries_svc
from rota.services import swaps as swaps_svc
from tests.factories import (MON, make_absence, make_clinician, make_entry,
                             make_session_type)

pytestmark = pytest.mark.django_db
User = get_user_model()
TUE = MON + timedelta(days=1)
FRI = MON + timedelta(days=4)


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


# --------------------------------------------------------------------------
# Two kinds of swap, told apart from the rota: WORK (both work both sessions,
# what they do is traded) and PEOPLE (each works only their own, the sessions
# change hands). Found on staging, where the first real proposal was the
# PEOPLE kind and the app only knew WORK.
# --------------------------------------------------------------------------

@pytest.fixture
def cover(db):
    """Alice works Fri PM only (Research); Beth works Mon AM only (Routine):
    the cover-for-each-other case, accepted and awaiting an admin."""
    research, routine = make_session_type("Research"), make_session_type("Routine")
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    make_entry(a, day=FRI, part="PM", session_type=research)
    make_entry(b, day=MON, part="AM", session_type=routine)
    req = SwapRequest.objects.create(
        proposer=a, proposer_day=FRI, proposer_part="PM",
        colleague=b, colleague_day=MON, colleague_part="AM",
        status=SwapRequest.Status.ACCEPTED)
    return a, b, req


def test_kind_is_work_when_both_work_both_sessions(scenario):
    a, b, *_ = scenario
    req = _swap(a, b)
    assert swaps_svc.kind(req) == swaps_svc.WORK
    assert swaps_svc.describe(req) == ("Alice Adams and Beth Brown trade what they do "
                                       "on Mon 20 Jul AM/PM and Tue 21 Jul AM.")
    assert swaps_svc.validate(req) == []


def test_kind_is_people_when_each_works_only_their_own(cover):
    a, b, req = cover
    assert swaps_svc.kind(req) == swaps_svc.PEOPLE
    assert swaps_svc.describe(req) == ("Beth Brown takes Alice Adams's Fri 24 Jul PM; "
                                       "Alice Adams takes Beth Brown's Mon 20 Jul AM.")
    assert swaps_svc.validate(req) == []


def test_a_people_swap_changes_hands_and_keeps_what_each_session_is(cover, admin_user):
    a, b, req = cover
    swaps_svc.approve(admin_user, req)
    fri = RotaEntry.objects.get(day=FRI, part="PM")
    mon = RotaEntry.objects.get(day=MON, part="AM")
    assert fri.clinician == b and fri.session_type.name == "Research" and fri.manually_set
    assert mon.clinician == a and mon.session_type.name == "Routine" and mon.manually_set
    assert RotaEntry.objects.count() == 2
    log = {(row.day, row.part): row for row in RotaEntryLog.objects.filter(action="swapped")}
    assert log[(FRI, "PM")].clinician_name == "Beth Brown"
    assert log[(FRI, "PM")].detail == "took over from Alice Adams"
    assert log[(MON, "AM")].clinician_name == "Alice Adams"
    assert log[(MON, "AM")].detail == "took over from Beth Brown"
    req.refresh_from_db()
    assert req.status == SwapRequest.Status.APPROVED
    assert req.decided_by == admin_user and req.decided_at is not None


def test_a_full_duty_day_changes_hands_whole(admin_user):
    duty, routine = make_session_type("Duty"), make_session_type("Routine")
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    entries_svc.assign_full_day(None, a, MON, duty, published=True)
    make_entry(b, day=TUE, part="AM", session_type=routine)
    req = SwapRequest.objects.create(
        proposer=a, proposer_day=MON, proposer_part="PM",
        colleague=b, colleague_day=TUE, colleague_part="AM",
        status=SwapRequest.Status.ACCEPTED)
    assert swaps_svc.kind(req) == swaps_svc.PEOPLE
    assert swaps_svc.describe(req).startswith("Beth Brown takes Alice Adams's Mon 20 Jul AM/PM;")
    swaps_svc.approve(admin_user, req)
    mon = {e.part: e for e in RotaEntry.objects.filter(day=MON)}
    assert mon["AM"].clinician == b and mon["PM"].clinician == b
    assert mon["AM"].allocation_group is not None
    assert mon["AM"].allocation_group == mon["PM"].allocation_group
    assert RotaEntry.objects.get(day=TUE, part="AM").clinician == a


def test_neither_pattern_is_refused_with_the_facts(scenario):
    a, b, duty, routine = scenario
    RotaEntry.objects.filter(clinician=b, day=MON, part="PM").delete()
    req = _swap(a, b)
    assert swaps_svc.kind(req) is None
    [problem] = swaps_svc.validate(req)
    assert problem.startswith("This swap fits neither pattern — ")
    assert "Beth Brown already has a session on Mon 20 Jul AM" in problem
    assert "Beth Brown has no session on Mon 20 Jul PM" in problem
    assert "Alice Adams already has a session on Tue 21 Jul AM" in problem
    assert problem.endswith("or neither works the other's and they cover for each other.")
    assert swaps_svc.describe(req) == ""
    with pytest.raises(ValueError):
        req.status = SwapRequest.Status.ACCEPTED
        swaps_svc.approve(None, req)


def test_a_people_swap_is_refused_when_the_receiver_is_on_leave(cover):
    a, b, req = cover
    make_absence(b, FRI)  # Beth would be taking Alice's Friday
    assert swaps_svc.validate(req) == [
        "Beth Brown is on leave on Fri 24 Jul PM (from Breathe) and cannot take that session."]


def test_a_paired_session_never_changes_hands(cover):
    a, b, req = cover
    RotaEntry.objects.filter(clinician=a, day=FRI).update(companion_group=uuid.uuid4())
    assert swaps_svc.validate(req) == [
        "Alice Adams's Fri 24 Jul PM is a paired session (mentoring) and cannot be swapped."]


def test_a_session_that_has_gone_is_named_first_and_leave_still_after_it(cover):
    a, b, req = cover
    RotaEntry.objects.filter(clinician=a).delete()
    assert swaps_svc.validate(req) == ["Alice Adams has no session on Fri 24 Jul PM."]
    make_absence(b, FRI)  # Beth would take Alice's Friday, and is off
    assert swaps_svc.validate(req) == [
        "Alice Adams has no session on Fri 24 Jul PM.",
        "Beth Brown is on leave on Fri 24 Jul PM (from Breathe) and cannot take that session."]


def test_a_swap_that_fits_neither_pattern_is_refused_when_proposed(client, pair):
    a, b, mine, theirs = pair
    # Alice also has a session in Beth's slot: neither a trade nor a cover.
    make_entry(a, day=theirs.day, part=theirs.part, session_type=theirs.session_type)
    resp = client.post("/me/swap/new/", {"my_entry_id": mine.id,
                                          "their_entry_id": theirs.id})
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "This swap fits neither pattern" in html
    assert "Alice Adams already has a session on" in html
    assert not SwapRequest.objects.exists()


def test_the_requests_page_says_what_applying_would_do(admin_client, cover):
    a, b, req = cover
    html = admin_client.get("/requests/").content.decode()
    assert escape("Beth Brown takes Alice Adams's Fri 24 Jul PM; "
                  "Alice Adams takes Beth Brown's Mon 20 Jul AM.") in html
    assert "disabled" not in html.split("Approve")[0].rsplit("<form", 1)[-1]
