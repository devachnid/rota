import pytest

from rota.models import RotaEntry, RotaEntryLog
from rota.services import entries
from tests.factories import MON, make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db


def test_assign_creates_entry_and_log(admin_user):
    c = make_clinician()
    st = make_session_type("Routine")
    e = entries.assign(admin_user, c, MON, "AM", st)
    assert e.session_type == st and not e.is_published and e.manually_set
    assert RotaEntryLog.objects.filter(action="created", clinician_name=c.name).exists()


def test_assign_replaces_existing_in_place(admin_user):
    c = make_clinician()
    old = make_entry(c, session_type=make_session_type("Routine"))
    st2 = make_session_type("Admin", category="NON_CLINICAL")
    e = entries.assign(admin_user, c, MON, "AM", st2)
    assert e.pk == old.pk and e.session_type == st2
    assert e.is_published  # replacing a published entry keeps it published
    assert RotaEntryLog.objects.filter(action="changed").exists()


def test_full_day_pair_is_linked(admin_user):
    c = make_clinician()
    duty = make_session_type("Duty", fairness_tracked=True)
    am, pm = entries.assign_full_day(admin_user, c, MON, duty)
    assert am.allocation_group and am.allocation_group == pm.allocation_group


def test_editing_half_splits_pair(admin_user):
    c, c2 = make_clinician(), make_clinician("Beth Brown")
    duty = make_session_type("Duty", fairness_tracked=True)
    am, pm = entries.assign_full_day(admin_user, c, MON, duty)
    entries.assign(admin_user, c, MON, "PM", make_session_type("Routine"))
    am.refresh_from_db()
    assert am.allocation_group is None


def test_clear_deletes_and_logs(admin_user):
    c = make_clinician()
    make_entry(c)
    entries.clear(admin_user, c, MON, "AM")
    assert not RotaEntry.objects.exists()
    assert RotaEntryLog.objects.filter(action="cleared").exists()


def test_publish_range(admin_user):
    c = make_clinician()
    make_entry(c, part="AM", is_published=False)
    make_entry(c, part="PM", is_published=False)
    n = entries.publish_range(admin_user, MON, MON)
    assert n == 2
    assert RotaEntry.objects.filter(is_published=True).count() == 2
