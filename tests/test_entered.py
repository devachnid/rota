"""A session keyed into the clinical system's appointment screen carries
when and by whom. Anything that changes what the session is clears it."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model

from rota.models import RotaEntry, RotaEntryLog, Site, SwapRequest
from rota.services import entries as entries_svc
from rota.services import swaps as swaps_svc
from tests.factories import MON, make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db
User = get_user_model()
TUE = MON + timedelta(days=1)


def test_set_entered_stamps_and_logs(admin_user):
    e = make_entry(make_clinician())
    entries_svc.set_entered(admin_user, e, True)
    e.refresh_from_db()
    assert e.entered_at is not None and e.entered_by == admin_user
    assert RotaEntryLog.objects.filter(action="entered", day=MON, part="AM").exists()
    entries_svc.set_entered(admin_user, e, False)
    e.refresh_from_db()
    assert e.entered_at is None and e.entered_by is None
    assert RotaEntryLog.objects.filter(action="unentered").exists()


def test_a_note_only_save_keeps_the_mark(admin_user):
    c = make_clinician()
    rout = make_session_type("Routine")
    e = make_entry(c, session_type=rout)
    entries_svc.set_entered(admin_user, e, True)
    entries_svc.assign(admin_user, c, MON, "AM", rout, note="ring first")
    e.refresh_from_db()
    assert e.entered_at is not None and e.note == "ring first"


def test_a_type_change_clears_the_mark(admin_user):
    c = make_clinician()
    e = make_entry(c, session_type=make_session_type("Routine"))
    entries_svc.set_entered(admin_user, e, True)
    entries_svc.assign(admin_user, c, MON, "AM", make_session_type("Duty", code="DUTY"))
    e.refresh_from_db()
    assert e.entered_at is None and e.entered_by is None


def test_a_site_change_clears_the_mark(admin_user):
    c = make_clinician()
    rout = make_session_type("Routine")
    e = make_entry(c, session_type=rout)
    entries_svc.set_entered(admin_user, e, True)
    entries_svc.assign(admin_user, c, MON, "AM", rout, site=Site.objects.create(name="Branch"))
    e.refresh_from_db()
    assert e.entered_at is None


def test_publishing_keeps_the_mark(admin_user):
    e = make_entry(make_clinician(), is_published=False)
    entries_svc.set_entered(admin_user, e, True)
    entries_svc.publish_range(admin_user, MON, MON)
    e.refresh_from_db()
    assert e.is_published and e.entered_at is not None


def test_a_fill_rerun_leaves_a_published_marked_session_alone(admin_user):
    from rota.models import PracticeSettings
    from rota.services.fill import run_fill
    PracticeSettings.load()
    e = make_entry(make_clinician())            # published, manually set
    entries_svc.set_entered(admin_user, e, True)
    run_fill(admin_user, MON, MON)
    e.refresh_from_db()
    assert e.entered_at is not None


def _accepted_swap(admin_user):
    """The scenario tests/test_swaps.py proves applies: Alice has Duty Mon
    (full day) + Routine Tue AM; Beth has Routine Mon AM/PM + Duty Tue AM.
    Alice offers Mon AM for Beth's Tue AM — a trade of the work. Every
    entry the swap touches is marked first."""
    duty = make_session_type("Duty", code="DUTY", fairness_tracked=True)
    rout = make_session_type("Routine")
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    entries_svc.assign_full_day(None, a, MON, duty, published=True)
    make_entry(a, day=TUE, part="AM", session_type=rout)
    make_entry(b, day=MON, part="AM", session_type=rout)
    make_entry(b, day=MON, part="PM", session_type=rout)
    entries_svc.assign(None, b, TUE, "AM", duty, published=True)
    for e in RotaEntry.objects.all():
        entries_svc.set_entered(admin_user, e, True)
    b.user = User.objects.create_user(email="beth@example.com", password="pw")
    b.save()
    req = SwapRequest.objects.create(
        proposer=a, proposer_day=MON, proposer_part="AM",
        colleague=b, colleague_day=TUE, colleague_part="AM")
    swaps_svc.accept(req, b.user)
    return req


def test_an_approved_swap_clears_the_mark_on_every_entry_it_touches(admin_user):
    req = _accepted_swap(admin_user)
    swaps_svc.approve(admin_user, req)
    touched = RotaEntry.objects.filter(day__in=(MON, TUE), part="AM")
    assert touched.count() == 4
    assert not touched.filter(entered_at__isnull=False).exists()
    # Beth's Mon PM and Alice's Mon PM are the swap's linked full-day
    # halves; the swap moves them too, so they are cleared as well.
    assert not RotaEntry.objects.filter(entered_at__isnull=False).exists()
