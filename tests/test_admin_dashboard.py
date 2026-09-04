"""The dashboard reads the database. Each setup step flips on one exact
condition; each health line counts one thing and links to its fix; the
whole page costs a fixed number of queries."""

from datetime import date, timedelta

import pytest
from django.utils import timezone

from rota.admin_dashboard import health, setup_steps
from rota.models import (BreatheSyncRun, ClinicianGroup, CoverageRule,
                         PracticeSettings, SessionType, Site)
from tests.factories import (make_clinician, make_group, make_pattern,
                             make_session_type)

pytestmark = pytest.mark.django_db


def _step(title):
    return next(s for s in setup_steps()["steps"] if s["title"] == title)


def test_practice_settings_step_needs_open_days_and_a_default_type():
    s = PracticeSettings.load()
    assert not _step("Practice settings")["done"]
    s.default_fill_session_type = make_session_type("Routine")
    s.save()
    assert _step("Practice settings")["done"]
    s.open_weekdays = ""
    s.save()
    assert not _step("Practice settings")["done"]


def test_sites_and_rules_steps():
    assert not _step("Sites")["done"] and not _step("Coverage rules")["done"]
    Site.objects.create(name="Main")
    CoverageRule.objects.create(session_type=make_session_type("Duty"))
    assert _step("Sites")["done"] and _step("Coverage rules")["done"]


def test_groups_step_needs_exactly_one_locum_group():
    make_group("Partners")
    assert not _step("Clinician groups")["done"]
    make_group("Locum", is_locum_group=True, display_order=99)
    assert _step("Clinician groups")["done"]


def test_session_types_step_needs_a_clinical_and_an_absence_type():
    # Migration 0022_breathe seeds three ABSENCE-category types (AL/SICK/OTH)
    # and maps them, so a fresh test DB is not actually blank on this axis.
    # Clear both, PROTECT-guarded mapping first, for a genuine blank slate.
    from rota.models import BreatheLeaveMapping
    BreatheLeaveMapping.objects.all().delete()
    SessionType.objects.filter(category="ABSENCE").delete()
    make_session_type("Routine")
    assert not _step("Session types")["done"]
    make_session_type("Annual Leave", code="AL", category="ABSENCE")
    assert _step("Session types")["done"]


def test_clinicians_and_patterns_steps():
    assert not _step("Clinicians")["done"]
    c = make_clinician("Ann Able")
    assert _step("Clinicians")["done"] and not _step("Working patterns")["done"]
    assert "1 clinician" in _step("Working patterns")["detail"]
    make_pattern(c)
    assert _step("Working patterns")["done"]


def test_breathe_step_needs_key_sync_and_links(settings):
    c = make_clinician("Ann Able", breathe_employee_id=1)
    assert not _step("Breathe")["done"]
    settings.BREATHE_API_KEY = "set"
    assert not _step("Breathe")["done"]
    BreatheSyncRun.objects.create(started=timezone.now(), finished=timezone.now(), ok=True)
    assert _step("Breathe")["done"]
    make_clinician("Bob Unlinked")
    assert not _step("Breathe")["done"]


def test_the_headline_counts_and_names_the_next_step():
    Site.objects.create(name="Main")
    steps = setup_steps()
    assert steps["done"] == 1 and steps["total"] == 8
    assert steps["next"]["title"] == "Practice settings"
    assert not steps["complete"]


def test_health_lines_count_and_link():
    make_clinician("No Pattern")
    lines = {h["label"]: h for h in health()}
    assert lines["Clinicians with no working pattern"]["count"] == 1
    assert "missing=1" in lines["Clinicians with no working pattern"]["url"]
    assert lines["Clinicians not linked to Breathe"]["count"] == 1
    assert lines["Breathe sync"]["detail"] == "not configured"


def test_the_dashboard_renders_both_cards(admin_client):
    PracticeSettings.load()
    html = admin_client.get("/admin/").content.decode()
    assert "Setup" in html and "Health" in html and "of 8" in html


def test_the_dashboard_does_not_query_per_clinician(admin_client):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    PracticeSettings.load()
    for i in range(3):
        make_pattern(make_clinician(f"Doc {i}", initials=f"D{i}"))
    admin_client.get("/admin/")
    with CaptureQueriesContext(connection) as ctx:
        admin_client.get("/admin/")
    baseline = len(ctx)
    for i in range(3, 13):
        make_pattern(make_clinician(f"Doc {i}", initials=f"D{i}"))
    with CaptureQueriesContext(connection) as ctx:
        admin_client.get("/admin/")
    assert len(ctx) == baseline
