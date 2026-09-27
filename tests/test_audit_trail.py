"""The audit log keeps the whole story: edits made in the Django admin are in
it, and who made each change survives their login being deleted."""

import importlib

import pytest
from django.apps import apps as global_apps
from django.contrib.auth import get_user_model

from rota.models import RotaEntry, RotaEntryLog
from tests.factories import MON, make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db
User = get_user_model()


def _change_form(entry, **changes):
    data = {"day": entry.day.isoformat(), "part": entry.part,
            "clinician": entry.clinician_id, "session_type": entry.session_type_id,
            "site": "", "note": entry.note, "is_published": "on", "manually_set": "on",
            "fill_reason": "", "allocation_group": "", "companion_group": ""}
    data.update(changes)
    return data


# --- edits in the admin -----------------------------------------------------------

def test_a_change_in_the_admin_is_logged_with_who_and_what(admin_client, admin_user):
    entry = make_entry(make_clinician("Ann Invented"), session_type=make_session_type("Routine", code="ROUT"))
    duty = make_session_type("Duty", code="DUTY")
    resp = admin_client.post(f"/admin/rota/rotaentry/{entry.pk}/change/",
                             _change_form(entry, session_type=duty.pk))
    assert resp.status_code == 302, resp.content.decode()[:3000]
    (log,) = RotaEntryLog.objects.all()
    assert (log.action, log.actor, log.clinician_name) == ("changed", admin_user, "Ann Invented")
    assert log.detail == "in the admin: session_type"


def test_a_deletion_in_the_admin_is_logged(admin_client, admin_user):
    entry = make_entry(make_clinician("Ann Invented"), session_type=make_session_type("Routine", code="ROUT"))
    resp = admin_client.post(f"/admin/rota/rotaentry/{entry.pk}/delete/", {"post": "yes"})
    assert resp.status_code == 302
    assert not RotaEntry.objects.exists()
    (log,) = RotaEntryLog.objects.all()
    assert (log.action, log.actor, log.detail) == ("cleared", admin_user, "in the admin: ROUT")


def test_a_bulk_deletion_logs_every_entry(admin_client):
    c = make_clinician("Ann Invented")
    st = make_session_type("Routine", code="ROUT")
    entries = [make_entry(c, day=MON, part=p, session_type=st) for p in ("AM", "PM")]
    admin_client.post("/admin/rota/rotaentry/", {
        "action": "delete_selected", "_selected_action": [e.pk for e in entries],
        "post": "yes"})
    assert not RotaEntry.objects.exists()
    assert sorted(RotaEntryLog.objects.values_list("part", flat=True)) == ["AM", "PM"]


# --- names survive the login ----------------------------------------------------------

def test_the_actors_name_survives_their_login_being_deleted(staff_client, admin_user):
    log = RotaEntryLog.objects.create(day=MON, part="AM", clinician_name="Ann Invented",
                                      actor=admin_user, action="created")
    assert log.actor_name == admin_user.email
    admin_user.delete()
    log.refresh_from_db()
    assert log.actor is None and log.actor_name == "admin@example.com"
    html = staff_client.get("/admin/rota/rotaentrylog/").content.decode()
    assert "admin@example.com" in html


def test_the_migration_backfills_existing_rows(admin_user):
    log = RotaEntryLog.objects.create(day=MON, action="created", actor=admin_user)
    RotaEntryLog.objects.filter(pk=log.pk).update(actor_name="")
    migration = importlib.import_module("rota.migrations.0033_rotaentrylog_actor_name")
    migration.backfill(global_apps, None)
    log.refresh_from_db()
    assert log.actor_name == admin_user.email


# --- who may delete a login ------------------------------------------------------------

def test_a_rota_admin_cannot_delete_a_login(admin_client, gp_user):
    """Deactivating does everything deleting is for and keeps the history;
    a rota admin could previously delete any non-superuser login, their own
    included."""
    assert admin_client.get(f"/admin/accounts/user/{gp_user.pk}/delete/").status_code == 403
    admin_client.post("/admin/accounts/user/", {
        "action": "delete_selected", "_selected_action": [gp_user.pk], "post": "yes"})
    assert User.objects.filter(pk=gp_user.pk).exists()
    assert "delete_selected" not in admin_client.get("/admin/accounts/user/").content.decode()


def test_a_superuser_still_can(staff_client, gp_user):
    resp = staff_client.post(f"/admin/accounts/user/{gp_user.pk}/delete/", {"post": "yes"})
    assert resp.status_code == 302
    assert not User.objects.filter(pk=gp_user.pk).exists()
