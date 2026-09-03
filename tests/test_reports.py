from datetime import date, timedelta

import pytest

from rota.models import CoverageRule, PracticeSettings
from rota.services.calendar import is_open
from tests.factories import (make_absence, make_clinician, make_entry,
                             make_pattern, make_session_type)

pytestmark = pytest.mark.django_db


def test_fairness_report_shows_balance(admin_client):
    PracticeSettings.load()
    duty = make_session_type("Duty", fairness_tracked=True)
    a = make_clinician("Alice Adams")
    make_pattern(a)
    today = date.today()
    make_entry(a, day=today - timedelta(days=7), part="AM", session_type=duty)
    html = admin_client.get("/reports/fairness/").content.decode()
    assert "Alice Adams" in html and "Duty" in html


def test_staffing_report_lists_gaps(admin_client):
    PracticeSettings.objects.update_or_create(
        pk=1, defaults={"min_clinical_per_session": 1})
    duty = make_session_type("Duty", fairness_tracked=True)
    CoverageRule.objects.create(session_type=duty,
                                unit=CoverageRule.Unit.PER_DAY, priority=1)
    html = admin_client.get("/reports/staffing/?weeks=1").content.decode()
    assert "No Duty cover" in html


def test_staffing_weeks_clamped(admin_client):
    PracticeSettings.load()
    resp = admin_client.get("/reports/staffing/?weeks=5000")
    assert resp.status_code == 200
    assert b"next 26 weeks" in resp.content
    resp = admin_client.get("/reports/staffing/?weeks=0")
    assert b"next 1 weeks" in resp.content


def test_staffing_report_hides_breathe_line_from_gps(gp_client, admin_client):
    """The Breathe naming line is admin-only, even on a report every
    clinician can otherwise read — see docs/admin/day-to-day.md."""
    PracticeSettings.load()
    rout = make_session_type("Routine", code="ROUT")
    c = make_clinician("Ann Able")
    make_pattern(c)
    d = date.today()
    while not is_open(d):
        d += timedelta(days=1)
    make_entry(c, day=d, part="AM", session_type=rout)
    make_absence(c, d)
    gp_html = gp_client.get("/reports/staffing/").content.decode()
    admin_html = admin_client.get("/reports/staffing/").content.decode()
    assert "On Breathe leave but rostered" not in gp_html
    assert "On Breathe leave but rostered" in admin_html


def test_fairness_report_hides_drafts_from_gps(gp_client, admin_client):
    PracticeSettings.load()
    duty = make_session_type("Duty", fairness_tracked=True)
    a = make_clinician("Alice Adams")
    make_pattern(a)
    make_entry(a, day=date.today() - timedelta(days=7), part="AM",
               session_type=duty, is_published=False)
    gp_html = gp_client.get("/reports/fairness/").content.decode()
    admin_html = admin_client.get("/reports/fairness/").content.decode()
    assert "<td>0</td>" in gp_html and "<td>1</td>" not in gp_html
    assert "<td>1</td>" in admin_html
