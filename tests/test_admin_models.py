"""The model admins, rebuilt: fieldsets with the docs' sentences, search,
inlines, and a clinician page that says what pattern someone works."""

from datetime import date

import pytest

from rota.models import PatternSlot
from tests.factories import (make_clinician, make_group, make_pattern,
                             make_session_type)

pytestmark = pytest.mark.django_db


def _change(client, obj):
    opts = obj._meta
    return client.get(f"/admin/{opts.app_label}/{opts.model_name}/{obj.pk}/change/").content.decode()


# ------------------------------------------------------------ clinicians ---

def test_the_clinician_page_has_the_four_fieldsets_and_two_inlines(admin_client):
    c = make_clinician("Ann Able")
    html = _change(admin_client, c)
    for title in ("Who", "Availability", "Roles", "Leave from Breathe"):
        assert title in html, title
    assert "Trainee profile" in html and "Recurring commitment" in html


def test_the_clinician_page_summarises_the_pattern_in_force(admin_client):
    c = make_clinician("Pat Tern")
    make_pattern(c, weekdays=(0, 3), parts=("AM", "PM"), effective_from=date(2025, 9, 1))
    PatternSlot.objects.create(clinician=c, weekday=1, part="AM", works=True,
                               effective_from=date(2025, 9, 1))
    html = _change(admin_client, c)
    assert "Mon AM/PM · Tue AM · Thu AM/PM" in html
    assert "since 1 Sep 2025" in html
    assert "/admin/rota/patternslot/bulk/?clinician_id=" in html


def test_a_clinician_without_a_pattern_says_so_in_the_list(admin_client):
    make_clinician("No Pattern")
    html = admin_client.get("/admin/rota/clinician/").content.decode()
    assert "No pattern yet" in html


def test_the_pattern_column_costs_no_query_per_clinician(admin_client):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    def add(n):
        for i in range(n):
            make_pattern(make_clinician(f"Doc {i}", initials=f"D{i}"))

    add(2)
    admin_client.get("/admin/rota/clinician/")
    with CaptureQueriesContext(connection) as ctx:
        admin_client.get("/admin/rota/clinician/")
    baseline = len(ctx)
    add(8)
    with CaptureQueriesContext(connection) as ctx:
        admin_client.get("/admin/rota/clinician/")
    assert len(ctx) == baseline


def test_clinician_search_finds_by_name_initials_and_email(admin_client, gp_user):
    make_clinician("Alice Adams", user=gp_user)
    make_clinician("Bob Baker")
    for q in ("Alice", "AA", "gp@example.com"):
        html = admin_client.get(f"/admin/rota/clinician/?q={q}").content.decode()
        assert "Alice Adams" in html and "Bob Baker" not in html, q


def test_the_deactivate_action_and_deletion_guard_survive(admin_client):
    from tests.factories import make_entry
    c = make_clinician("Guarded")
    make_entry(c, is_published=True)
    resp = admin_client.get(f"/admin/rota/clinician/{c.pk}/delete/")
    assert "Deactivate this clinician instead" in resp.content.decode()
    resp = admin_client.post("/admin/rota/clinician/", {
        "action": "deactivate_clinicians", "_selected_action": [c.pk]}, follow=True)
    c.refresh_from_db()
    assert not c.active


# ----------------------------------------------------- groups & trainees ---

def test_group_order_and_minimum_are_editable_in_the_list(admin_client):
    make_group("Partners")
    html = admin_client.get("/admin/rota/cliniciangroup/").content.decode()
    assert 'name="form-0-display_order"' in html and 'name="form-0-min_per_session"' in html


def test_trainee_profiles_list_and_search(admin_client):
    from tests.factories import make_trainee
    t = make_trainee(make_clinician("Terry Trainee"))
    html = admin_client.get("/admin/rota/traineeprofile/?q=Terry").content.decode()
    assert "Terry Trainee" in html and t.stage in html


# --------------------------------------------------------- login accounts ---

def test_a_rota_admin_edits_accounts_without_the_system_fieldset(admin_client, gp_user, staff_client):
    make_clinician("Gwen Peters", user=gp_user)
    html = _change(admin_client, gp_user)
    assert "Rota admin" in html or "is_rota_admin" in html
    assert "Gwen Peters" in html, "the linked clinician is shown"
    assert 'name="is_superuser"' not in html
    assert 'name="is_superuser"' in _change(staff_client, gp_user)


def test_an_account_can_be_added_through_unfolds_form(admin_client):
    resp = admin_client.post("/admin/accounts/user/add/", {
        "email": "new@example.com", "password1": "correct-horse-battery",
        "password2": "correct-horse-battery", "is_rota_admin": "on"}, follow=True)
    assert resp.status_code == 200
    from accounts.models import User
    assert User.objects.get(email="new@example.com").is_rota_admin


# ------------------------------------------------------ help text & names ---

def test_the_models_read_as_a_manager_would_say_them():
    from accounts.models import User
    from rota.models import PracticeSettings, RotaEntry, RotaEntryLog, TraineeProfile
    assert str(PracticeSettings._meta.verbose_name_plural) == "practice settings"
    assert str(RotaEntry._meta.verbose_name_plural) == "rota entries"
    assert str(RotaEntryLog._meta.verbose_name_plural) == "audit log"
    assert str(TraineeProfile._meta.verbose_name_plural) == "trainee profiles"
    assert str(User._meta.verbose_name_plural) == "login accounts"


@pytest.mark.parametrize("model,field", [
    ("Clinician", "initials"), ("Clinician", "active"), ("ClinicianGroup", "is_locum_group"),
    ("SessionType", "code"), ("SessionType", "category"), ("SessionType", "fairness_tracked"),
    ("CoverageRule", "count"), ("CoverageRule", "weekdays"),
    ("PracticeSettings", "min_clinical_per_session"), ("PracticeSettings", "default_fill_session_type"),
    ("ClosedDay", "reason"), ("DayNote", "text"),
])
def test_every_field_a_manager_meets_explains_itself(model, field):
    from rota import models
    assert getattr(models, model)._meta.get_field(field).help_text, f"{model}.{field}"


# ------------------------------------------------------ sessions & rules ---

def test_the_session_type_page_has_its_fieldsets_and_the_large_swatch(admin_client):
    st = make_session_type("Duty", code="DUTY")
    html = _change(admin_client, st)
    for title in ("Identity", "Where it appears", "Fairness", "Who may do it", "Clashes"):
        assert title in html, title


def test_coverage_rules_render_checkboxes_and_save_the_same_string(admin_client):
    st = make_session_type("Duty")
    html = admin_client.get("/admin/rota/coveragerule/add/").content.decode()
    assert 'name="weekdays" value="0"' in html and 'name="months" value="12"' in html
    assert "worked example" in html.lower() or "Duty, per full day" in html
    resp = admin_client.post("/admin/rota/coveragerule/add/", {
        "session_type": st.pk, "unit": "DAY", "frequency": "SLOT", "count": 1,
        "priority": 1, "parts": "BOTH", "weekdays": ["0", "1", "2", "3", "4"]})
    assert resp.status_code == 302, resp.content.decode()[:500]
    from rota.models import CoverageRule
    assert CoverageRule.objects.get().weekdays == "0,1,2,3,4"


def test_stage_rules_edit_in_the_list_and_cannot_be_deleted(admin_client):
    from rota.models import TraineeStageRule
    rule = TraineeStageRule.objects.get(stage="ST1")
    html = admin_client.get("/admin/rota/traineestagerule/").content.decode()
    assert 'name="form-0-vts_per_week"' in html
    assert admin_client.get(f"/admin/rota/traineestagerule/{rule.pk}/delete/").status_code == 403


def test_a_commitment_offers_weekdays_by_name(admin_client):
    html = admin_client.get("/admin/rota/recurringcommitment/add/").content.decode()
    assert '<option value="3">Thursday</option>' in html


# --------------------------------------------------------------- calendar ---

def test_closed_days_have_a_date_hierarchy_and_search(admin_client):
    from rota.models import ClosedDay
    ClosedDay.objects.create(day=date(2026, 12, 25), reason="Christmas")
    html = admin_client.get("/admin/rota/closedday/").content.decode()
    assert "2026" in html and "Christmas" in html
    assert "Christmas" in admin_client.get("/admin/rota/closedday/?q=Christ").content.decode()


# ------------------------------------------------------- practice settings ---

def test_the_settings_changelist_opens_the_singleton(admin_client):
    from rota.models import PracticeSettings
    s = PracticeSettings.load()
    resp = admin_client.get("/admin/rota/practicesettings/")
    assert resp.status_code == 302
    assert resp["Location"].endswith(f"/admin/rota/practicesettings/{s.pk}/change/")


def test_settings_render_weekday_checkboxes_and_warn_on_no_days(admin_client):
    from rota.models import PracticeSettings
    s = PracticeSettings.load()
    html = _change(admin_client, s)
    assert 'name="open_weekdays" value="0"' in html and "Trainees" in html
    resp = admin_client.post(f"/admin/rota/practicesettings/{s.pk}/change/", {
        "min_clinical_per_session": 2, "open_weekdays": []}, follow=True)
    assert "open on no days" in resp.content.decode()
    s.refresh_from_db()
    assert s.open_weekdays == ""
