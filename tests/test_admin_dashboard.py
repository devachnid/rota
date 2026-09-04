"""The dashboard reads the database. Each setup step flips on one exact
condition; each health line counts one thing and links to its fix; the
whole page costs a fixed number of queries."""

import datetime as dt
from datetime import date, timedelta

import pytest
from django.utils import timezone

from rota.admin_dashboard import health, setup_steps
from rota.models import (BreatheSyncRun, CoverageRule,
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
    SessionType.objects.filter(category=SessionType.Category.ABSENCE).delete()
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
    make_clinician("Ann Able", breathe_employee_id=1)
    assert not _step("Breathe")["done"]
    assert _step("Breathe")["detail"] == "BREATHE_API_KEY is not set"
    assert _step("Breathe")["url"].endswith("/breathesyncrun/status/")
    settings.BREATHE_API_KEY = "set"
    assert not _step("Breathe")["done"]
    assert _step("Breathe")["detail"] == "no successful sync yet"
    assert _step("Breathe")["url"].endswith("/breathesyncrun/status/")
    BreatheSyncRun.objects.create(started=timezone.now(), finished=timezone.now(), ok=True)
    assert _step("Breathe")["done"]
    assert _step("Breathe")["detail"] == "key set, synced, everyone linked"
    make_clinician("Bob Unlinked")
    assert not _step("Breathe")["done"]
    assert _step("Breathe")["detail"] == "1 not linked"
    assert "breathe=unlinked" in _step("Breathe")["url"]


def test_the_headline_counts_and_names_the_next_step():
    Site.objects.create(name="Main")
    steps = setup_steps()
    assert steps["done"] == 1 and steps["total"] == 8
    assert steps["next"]["title"] == "Practice settings"
    assert not steps["complete"]


def test_health_lines_count_and_link(admin_client):
    from rota.models import LocumRequirement
    make_clinician("No Pattern")
    locum_group = make_group("Locum", is_locum_group=True, display_order=99)
    make_clinician("Loose Locum", group=locum_group)
    duty = make_session_type("Duty")
    today = date.today()
    LocumRequirement.objects.create(
        day=today + timedelta(days=3), part="AM", session_type=duty,
        status=LocumRequirement.Status.POSSIBLE)
    LocumRequirement.objects.create(
        day=today + timedelta(days=5), part="PM", session_type=duty,
        status=LocumRequirement.Status.APPROVED)
    LocumRequirement.objects.create(
        day=today + timedelta(days=30), part="AM", session_type=duty,
        status=LocumRequirement.Status.POSSIBLE)
    lines = {h["label"]: h for h in health()}
    assert lines["Clinicians with no working pattern"]["count"] == 1
    assert "missing=1" in lines["Clinicians with no working pattern"]["url"]
    # An unlinked locum-group clinician does not count, and the link this
    # count offers must filter the same clinicians it counted.
    assert lines["Clinicians not linked to Breathe"]["count"] == 1
    unlinked_url = lines["Clinicians not linked to Breathe"]["url"]
    assert "group__is_locum_group__exact=0" in unlinked_url
    assert admin_client.get(unlinked_url).status_code == 200
    assert lines["Breathe sync"]["detail"] == "not configured"
    locum = lines["Locum needs not yet advertised (next fortnight)"]
    assert locum["count"] == 2
    assert "status__in=POSSIBLE,APPROVED" in locum["url"]
    assert "day__gte=" in locum["url"]
    assert admin_client.get(locum["url"]).status_code == 200


def test_the_breathe_health_line_uses_local_time_not_utc(settings):
    """settings.TIME_ZONE is Europe/London — 1 July is BST (UTC+1), so an
    aware UTC 14:20 is a local 15:20. The dashboard must show the local
    hour, matching the |date filter the status page uses, not the raw
    UTC one."""
    settings.BREATHE_API_KEY = "set"
    started = dt.datetime(2026, 7, 1, 14, 20, tzinfo=dt.timezone.utc)
    finished = dt.datetime(2026, 7, 1, 14, 25, tzinfo=dt.timezone.utc)
    BreatheSyncRun.objects.create(started=started, finished=finished, ok=True)
    lines = {h["label"]: h for h in health()}
    detail = lines["Breathe sync"]["detail"]
    assert "15:20" in detail
    assert "14:20" not in detail


def test_the_dashboard_renders_both_cards(admin_client):
    PracticeSettings.load()
    html = admin_client.get("/admin/").content.decode()
    assert "Setup" in html and "Health" in html and "of 8" in html


def test_the_dashboard_collapses_when_setup_is_complete(admin_client, settings):
    ps = PracticeSettings.load()
    ps.default_fill_session_type = make_session_type("Routine")
    ps.save()
    Site.objects.create(name="Main")
    make_group("Partners")
    make_group("Locum", is_locum_group=True, display_order=99)
    make_session_type("Annual Leave", code="AL2", category="ABSENCE")
    CoverageRule.objects.create(session_type=make_session_type("Duty"))
    c = make_clinician("Ann Able", breathe_employee_id=1)
    make_pattern(c)
    settings.BREATHE_API_KEY = "set"
    BreatheSyncRun.objects.create(started=timezone.now(), finished=timezone.now(), ok=True)

    html = admin_client.get("/admin/").content.decode()
    assert "Setup complete." in html
    assert "<details" in html


def test_a_non_zero_health_line_is_red(admin_client):
    make_clinician("No Pattern")
    html = admin_client.get("/admin/").content.decode()
    label = "Clinicians with no working pattern"
    idx = html.index(label)
    li_start = html.rfind("<li", 0, idx)
    li_end = html.index("</li>", idx)
    assert "text-red-600" in html[li_start:li_end]


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
