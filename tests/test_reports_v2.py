from datetime import date, timedelta

import pytest

from rota.models import CoverageRule, PracticeSettings
from tests.factories import (MON, make_clinician, make_entry, make_pattern,
                             make_session_type, make_trainee)

pytestmark = pytest.mark.django_db


def test_trainee_report_expected_vs_delivered(admin_client):
    s = PracticeSettings.load()
    vts = make_session_type("VTS", category="NON_CLINICAL")
    s.vts_session_type = vts
    s.save()
    c = make_clinician("Terry Trainee")
    # exactly 3 whole weeks before this week's Monday -> 4 weeks due (weekday-safe)
    this_monday = date.today() - timedelta(days=date.today().weekday())
    start = this_monday - timedelta(days=21)
    make_trainee(clinician=c, stage="ST2", start=start)
    make_entry(c, day=date.today() - timedelta(days=7), part="AM",
               session_type=vts)
    html = admin_client.get("/reports/trainees/").content.decode()
    assert "Terry Trainee" in html
    assert "ST2" in html
    # 4 whole weeks elapsed -> expected 4, delivered 1
    assert ">4<" in html and ">1<" in html


def test_trainee_report_requires_login(client):
    assert client.get("/reports/trainees/").status_code == 302


def test_staffing_accrual_section_lists_behind_rules(admin_client):
    PracticeSettings.load()
    vas = make_session_type("Vas Clinic", fairness_tracked=True)
    CoverageRule.objects.create(
        session_type=vas, unit=CoverageRule.Unit.PER_SESSION,
        frequency=CoverageRule.Frequency.PER_WEEK, count=2,
        weekdays="0,1,2,3,4", priority=5)
    html = admin_client.get("/reports/staffing/?weeks=1").content.decode()
    assert "behind target" in html and "Vas Clinic" in html


def test_grid_tooltip_names_mentoring_partner(admin_client, admin_user):
    from rota.services import entries as entries_svc
    PracticeSettings.load()
    ment = make_session_type("Mentoring", category="NON_CLINICAL")
    a, b = make_clinician("Alice Adams"), make_clinician("Terry Trainee")
    make_pattern(a)
    make_pattern(b)
    entries_svc.assign_pair(admin_user, MON, "AM", a, b, ment, published=True)
    html = admin_client.get(f"/rota/?week={MON}").content.decode()
    assert "with Terry Trainee" in html
    assert "with Alice Adams" in html
