"""Deleting unpublished work in bulk.

One function decides what is "in scope" (drafts()) and one deletes it
(delete_drafts()). The fill engine's own re-run clearing calls the same
function, so there is one deletion rule in the codebase, not two.
"""

import uuid
from datetime import timedelta

import pytest

from rota.models import RotaEntry, RotaEntryLog
from rota.services import entries
from tests.factories import MON, make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db

FRI = MON + timedelta(days=4)
NEXT_MON = MON + timedelta(days=7)


@pytest.fixture
def world():
    """Inside MON..FRI: a published entry, a fill draft, a hand-placed draft.
    Outside it: a fill draft next week."""
    rout = make_session_type("Routine", code="ROUT")
    c = make_clinician()
    return {
        "published": make_entry(c, day=MON, part="AM", session_type=rout),
        "fill": make_entry(c, day=MON, part="PM", session_type=rout,
                           is_published=False, manually_set=False),
        "manual": make_entry(c, day=FRI, part="AM", session_type=rout,
                             is_published=False, manually_set=True),
        "later": make_entry(c, day=NEXT_MON, part="AM", session_type=rout,
                            is_published=False, manually_set=False),
    }


@pytest.mark.parametrize("include_manual,bounded,expected", [
    (True, False, {"fill", "manual", "later"}),
    (True, True, {"fill", "manual"}),
    (False, False, {"fill", "later"}),
    (False, True, {"fill"}),
])
def test_scope_is_the_product_of_manual_and_range(world, include_manual, bounded, expected):
    start, end = (MON, FRI) if bounded else (None, None)
    qs = entries.drafts(start, end, include_manual=include_manual)
    assert {k for k, e in world.items() if e in qs} == expected
    assert world["published"] not in qs


def test_delete_returns_the_counts_and_leaves_published_alone(world, admin_user):
    deleted, hand_placed = entries.delete_drafts(
        admin_user, MON, FRI, include_manual=True)
    assert (deleted, hand_placed) == (2, 1)
    assert set(RotaEntry.objects.values_list("pk", flat=True)) == {
        world["published"].pk, world["later"].pk}


def test_fill_scope_keeps_hand_placed_work(world, admin_user):
    deleted, hand_placed = entries.delete_drafts(
        admin_user, None, None, include_manual=False)
    assert (deleted, hand_placed) == (2, 0)
    assert RotaEntry.objects.filter(pk=world["manual"].pk).exists()


def test_the_deletion_is_logged_once(world, admin_user):
    entries.delete_drafts(admin_user, MON, FRI, include_manual=True)
    (log,) = RotaEntryLog.objects.filter(action="deleted drafts")
    assert log.actor == admin_user
    assert log.detail == f"{MON}..{FRI} (2 entries, 1 hand-placed)"


def test_an_unbounded_deletion_logs_all_dates(world, admin_user):
    entries.delete_drafts(admin_user, include_manual=True)
    log = RotaEntryLog.objects.get(action="deleted drafts")
    assert log.detail == "all dates (3 entries, 1 hand-placed)"


def test_a_published_survivor_loses_the_group_its_deleted_half_shared(admin_user):
    """A hand-placed full day, one half published by mistake: deleting the
    draft half must not leave the published half pointing at a pair that
    no longer exists — that is what the cell-by-cell clear() does too."""
    rout = make_session_type("Routine", code="ROUT")
    c = make_clinician()
    group = uuid.uuid4()
    kept = make_entry(c, day=MON, part="AM", session_type=rout, allocation_group=group)
    make_entry(c, day=MON, part="PM", session_type=rout, allocation_group=group,
               is_published=False)
    other = make_clinician("Other One")
    pair = uuid.uuid4()
    kept2 = make_entry(other, day=FRI, part="AM", session_type=rout, companion_group=pair)
    make_entry(c, day=FRI, part="AM", session_type=rout, companion_group=pair,
               is_published=False)

    entries.delete_drafts(admin_user, MON, FRI, include_manual=True)

    kept.refresh_from_db()
    kept2.refresh_from_db()
    assert kept.allocation_group is None
    assert kept2.companion_group is None


def test_run_fill_clears_through_the_same_rule(admin_user):
    """The engine deletes its own drafts before running. It now does so
    through delete_drafts(include_manual=False), and so logs it."""
    from rota.services.fill import run_fill
    rout = make_session_type("Routine", code="ROUT")
    c = make_clinician()
    make_entry(c, day=MON, part="AM", session_type=rout,
               is_published=False, manually_set=False)
    make_entry(c, day=MON, part="PM", session_type=rout,
               is_published=False, manually_set=True)
    run_fill(admin_user, MON, FRI)
    assert RotaEntry.objects.filter(is_published=False, manually_set=True).count() == 1
    assert RotaEntryLog.objects.filter(action="deleted drafts").exists()
