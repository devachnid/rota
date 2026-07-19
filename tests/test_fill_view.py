from datetime import timedelta

import pytest

from rota.models import CoverageRule, RotaEntry
from tests.factories import MON, make_clinician, make_pattern, make_session_type

pytestmark = pytest.mark.django_db


def test_fill_page_admin_only(gp_client):
    assert gp_client.get("/rota/fill/").status_code == 403


def test_post_runs_fill_and_reports(admin_client):
    duty = make_session_type("Duty", fairness_tracked=True)
    CoverageRule.objects.create(session_type=duty,
                                unit=CoverageRule.Unit.PER_DAY, priority=1)
    c = make_clinician()
    make_pattern(c)
    end = MON + timedelta(days=4)
    resp = admin_client.post("/rota/fill/", {
        "start": MON.isoformat(), "end": end.isoformat()})
    assert resp.status_code == 200
    assert b"10 draft session(s) created" in resp.content
    assert RotaEntry.objects.filter(is_published=False).count() == 10


def test_unfilled_slots_reported(admin_client):
    duty = make_session_type("Duty", fairness_tracked=True)
    CoverageRule.objects.create(session_type=duty,
                                unit=CoverageRule.Unit.PER_DAY, priority=1)
    resp = admin_client.post("/rota/fill/", {
        "start": MON.isoformat(), "end": MON.isoformat()})
    assert b"no eligible clinician" in resp.content
