"""Where a personal requirement's state is seen: a table on the staffing
report — requirement, clinician, last done, due, status — sorted overdue
first, and a count on the dashboard's Health card."""

from datetime import date, timedelta

import pytest

from rota.models import PracticeSettings
from rota.services.fill.accrual import week_monday
from tests.factories import make_clinician, make_entry, make_requirement, make_session_type

pytestmark = pytest.mark.django_db


def _setup():
    """Offsets from this week's Monday, so the expected states do not
    depend on which weekday the suite runs on."""
    PracticeSettings.load()
    today = date.today()
    wm = week_monday(today)
    nh = make_session_type("Nursing home round", code="NH")
    ann, bob, cal = (make_clinician(n) for n in ("Ann Able", "Bob Baker", "Cal Cole"))
    req = make_requirement(nh, [ann, bob, cal], interval_weeks=6,
                           active_from=today - timedelta(days=200))
    make_entry(ann, day=wm - timedelta(days=7), session_type=nh)         # due in 5 weeks: on track
    make_entry(bob, day=wm - timedelta(days=42), session_type=nh)        # due this week
    make_entry(cal, day=wm - timedelta(days=56), session_type=nh,
               is_published=False)                                       # a draft: 2 weeks overdue
    return today, nh, req


def test_the_report_lists_each_clinician_overdue_first(admin_client):
    today, nh, req = _setup()
    html = admin_client.get("/reports/staffing/").content.decode()
    assert '<h2 id="personal">Personal requirements</h2>' in html
    section = html[html.index('id="personal"'):]
    assert "Nursing home round, every 6 weeks" in section
    assert section.index("Cal Cole") < section.index("Bob Baker") < section.index("Ann Able")
    assert "2 weeks overdue" in section and "due this week" in section and "on track" in section
    assert f"week of {week_monday(today):%-d %b}" in section
    assert 'class="warn">2 weeks overdue' in section


def test_a_gp_sees_the_table_without_drafts(gp_client):
    today, nh, req = _setup()
    section = gp_client.get("/reports/staffing/").content.decode()
    section = section[section.index('id="personal"'):]
    # Cal's only session is a draft, so to a GP Cal has never done one:
    # due from active_from, long overdue.
    cal = section[section.index("Cal Cole"):section.index("Cal Cole") + 300]
    assert "never" in cal and "overdue" in cal


def test_no_section_without_a_live_requirement(admin_client):
    PracticeSettings.load()
    make_requirement(active_from=date.today() + timedelta(days=30))
    html = admin_client.get("/reports/staffing/").content.decode()
    assert 'id="personal"' not in html


def test_the_dashboard_counts_the_overdue():
    from rota.admin_dashboard import health
    _setup()
    lines = {h["label"]: h for h in health()}
    line = lines["Clinicians overdue a personal requirement"]
    assert line["count"] == 1 and line["url"].endswith("/reports/staffing/#personal")
