"""The dashboard reads the database. Each setup step flips on one exact
condition; each health line counts one thing and links to its fix; the
whole page costs a fixed number of queries."""

import datetime as dt
from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from rota.admin_dashboard import health, setup_steps
from rota.models import (TimeOffSyncRun, CoverageRule,
                         PracticeSettings, SessionType, Site)
from tests.factories import (make_clinician, make_group, make_pattern,
                             make_session_type)

pytestmark = pytest.mark.django_db
User = get_user_model()


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
    from rota.models import TimeOffMapping
    TimeOffMapping.objects.all().delete()
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


def _with_email(name, email, **kw):
    return make_clinician(name, user=User.objects.create_user(email=email, password="pw"), **kw)


def test_shift_central_step_needs_token_sync_and_everyone_matched(settings):
    _with_email("Ann Able", "ann@example.org")
    assert not _step("Shift Central")["done"]
    assert _step("Shift Central")["detail"] == "SHIFT_CENTRAL_URL or SHIFT_CENTRAL_TOKEN is not set"
    assert _step("Shift Central")["url"].endswith("/timeoffsyncrun/status/")
    settings.SHIFT_CENTRAL_URL, settings.SHIFT_CENTRAL_TOKEN = "https://shifts.example", "set"
    assert not _step("Shift Central")["done"]
    assert _step("Shift Central")["detail"] == "no successful sync yet"
    assert _step("Shift Central")["url"].endswith("/timeoffsyncrun/status/")
    TimeOffSyncRun.objects.create(started=timezone.now(), finished=timezone.now(), ok=True)
    assert _step("Shift Central")["done"]
    assert _step("Shift Central")["detail"] == "token set, synced, everyone matched"
    make_clinician("Bob NoEmail")
    assert not _step("Shift Central")["done"]
    assert _step("Shift Central")["detail"] == "1 without a login email"
    assert "user__isnull=True" in _step("Shift Central")["url"]


def test_shift_central_step_is_not_done_while_emails_are_unmatched(settings):
    settings.SHIFT_CENTRAL_URL, settings.SHIFT_CENTRAL_TOKEN = "https://shifts.example", "set"
    _with_email("Ann Able", "ann@example.org")
    TimeOffSyncRun.objects.create(started=timezone.now(), finished=timezone.now(), ok=True,
                                  n_unmatched=2, detail={"unmatched": ["x@example.org", "y@example.org"]})
    assert not _step("Shift Central")["done"]
    assert _step("Shift Central")["detail"] == "2 emails unmatched"
    assert _step("Shift Central")["url"].endswith("/timeoffsyncrun/status/")


def test_the_headline_counts_and_names_the_next_step(settings):
    settings.EMAIL_HOST = ""
    Site.objects.create(name="Main")
    steps = setup_steps()
    assert steps["done"] == 1 and steps["total"] == 9
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
    # A locum-group clinician without an email does not count, and the link
    # this count offers must filter the same clinicians it counted.
    assert lines["Clinicians without a login email"]["count"] == 1
    no_email_url = lines["Clinicians without a login email"]["url"]
    assert "group__is_locum_group__exact=0" in no_email_url
    assert admin_client.get(no_email_url).status_code == 200
    assert lines["Shift Central sync"]["detail"] == "not configured"
    locum = lines["Locum needs not yet advertised (next fortnight)"]
    assert locum["count"] == 2
    assert "status__in=POSSIBLE,APPROVED" in locum["url"]
    assert "day__gte=" in locum["url"]
    assert admin_client.get(locum["url"]).status_code == 200
    assert lines["Clinicians overdue a personal requirement"]["count"] == 0


def test_the_shift_central_health_line_uses_local_time_not_utc(settings):
    """settings.TIME_ZONE is Europe/London — 1 July is BST (UTC+1), so an
    aware UTC 14:20 is a local 15:20. The dashboard must show the local
    hour, matching the |date filter the status page uses, not the raw
    UTC one."""
    settings.SHIFT_CENTRAL_URL, settings.SHIFT_CENTRAL_TOKEN = "https://shifts.example", "set"
    started = dt.datetime(2026, 7, 1, 14, 20, tzinfo=dt.timezone.utc)
    finished = dt.datetime(2026, 7, 1, 14, 25, tzinfo=dt.timezone.utc)
    TimeOffSyncRun.objects.create(started=started, finished=finished, ok=True)
    lines = {h["label"]: h for h in health()}
    detail = lines["Shift Central sync"]["detail"]
    assert "15:20" in detail
    assert "14:20" not in detail


def test_the_dashboard_renders_both_cards(admin_client):
    PracticeSettings.load()
    html = admin_client.get("/admin/").content.decode()
    assert "Setup" in html and "Health" in html and "of 9" in html


def test_the_dashboard_collapses_when_setup_is_complete(admin_client, settings):
    ps = PracticeSettings.load()
    ps.default_fill_session_type = make_session_type("Routine")
    ps.save()
    Site.objects.create(name="Main")
    make_group("Partners")
    make_group("Locum", is_locum_group=True, display_order=99)
    make_session_type("Annual Leave", code="AL2", category="ABSENCE")
    CoverageRule.objects.create(session_type=make_session_type("Duty"))
    c = _with_email("Ann Able", "ann@example.org")
    make_pattern(c)
    settings.SHIFT_CENTRAL_URL, settings.SHIFT_CENTRAL_TOKEN = "https://shifts.example", "set"
    settings.EMAIL_HOST = "smtp.example"
    TimeOffSyncRun.objects.create(started=timezone.now(), finished=timezone.now(), ok=True)

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


def test_the_email_step_follows_email_host(settings, admin_client):
    settings.EMAIL_HOST = ""
    step = _step("Outgoing email")
    assert not step["done"] and "EMAIL_HOST" in step["detail"] and step["url"] is None
    html = admin_client.get("/admin/").content.decode()
    assert "Outgoing email" in html
    settings.EMAIL_HOST = "smtp.example"
    assert _step("Outgoing email")["done"]


def test_a_token_with_whitespace_or_no_url_reads_as_not_configured_everywhere(settings):
    settings.SHIFT_CENTRAL_URL, settings.SHIFT_CENTRAL_TOKEN = "https://shifts.example", "bad token"
    assert _step("Shift Central")["detail"] == "SHIFT_CENTRAL_URL or SHIFT_CENTRAL_TOKEN is not set"
    assert {h["label"]: h for h in health()}["Shift Central sync"]["detail"] == "not configured"
    settings.SHIFT_CENTRAL_URL, settings.SHIFT_CENTRAL_TOKEN = "", "good"
    assert _step("Shift Central")["detail"] == "SHIFT_CENTRAL_URL or SHIFT_CENTRAL_TOKEN is not set"
    assert {h["label"]: h for h in health()}["Shift Central sync"]["detail"] == "not configured"


def test_the_dashboards_link_lists_exactly_the_clinicians_without_a_login(admin_client):
    from rota.services.shift_central.links import without_email
    make_clinician("Has No Login")
    _with_email("Has A Login", "login@example.org")
    lines = {h["label"]: h for h in health()}
    line = lines["Clinicians without a login email"]
    assert line["count"] == without_email().count() == 1
    body = admin_client.get(line["url"]).content.decode()
    assert "Has No Login" in body and "Has A Login" not in body
