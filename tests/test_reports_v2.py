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


def test_trainee_report_survives_deleted_stage_rule(admin_client):
    from rota.models import TraineeStageRule
    s = PracticeSettings.load()
    vts = make_session_type("VTS", category="NON_CLINICAL")
    s.vts_session_type = vts
    s.save()
    c = make_clinician("Terry Trainee")
    make_trainee(clinician=c, stage="ST2", start=MON)
    TraineeStageRule.objects.filter(stage="ST2").delete()
    resp = admin_client.get("/reports/trainees/")
    assert resp.status_code == 200
    assert b"Terry Trainee" in resp.content


def test_trainee_report_respects_requirements_tracked_from(admin_client):
    # placement_start is 8 weeks ago (genuine backlog territory), but
    # requirements_tracked_from moves the anchor to 1 week before this
    # week's Monday -> only 2 weeks' worth should show as expected, not
    # the ~9 weeks a placement_start-anchored calculation would show.
    s = PracticeSettings.load()
    vts = make_session_type("VTS", category="NON_CLINICAL")
    s.vts_session_type = vts
    s.save()
    c = make_clinician("Terry Trainee")
    this_monday = date.today() - timedelta(days=date.today().weekday())
    placement_start = this_monday - timedelta(weeks=8)
    tracked_from = this_monday - timedelta(days=7)
    make_trainee(clinician=c, stage="ST2", start=placement_start,
                 requirements_tracked_from=tracked_from)
    html = admin_client.get("/reports/trainees/").content.decode()
    assert ">2<" in html
    assert ">9<" not in html and ">8<" not in html


def test_trainee_report_delivered_hidden_before_admin(admin_client, gp_client):
    # Drafts should count for an admin (who may have just run an unpublished
    # fill) but not for a GP, consistent with every other report.
    s = PracticeSettings.load()
    vts = make_session_type("VTS", category="NON_CLINICAL")
    s.vts_session_type = vts
    s.save()
    c = make_clinician("Terry Trainee")
    this_monday = date.today() - timedelta(days=date.today().weekday())
    make_trainee(clinician=c, stage="ST2", start=this_monday - timedelta(weeks=1))
    make_entry(c, day=this_monday, part="AM", session_type=vts, is_published=False)
    admin_html = admin_client.get("/reports/trainees/").content.decode()
    gp_html = gp_client.get("/reports/trainees/").content.decode()
    assert ">1<" in admin_html
    assert ">0<" in gp_html


def test_trainee_report_excludes_finished_placements(admin_client):
    c = make_clinician("Terry Trainee")
    today = date.today()
    make_trainee(clinician=c, stage="ST2",
                 start=today - timedelta(days=400),
                 end=today - timedelta(days=1))
    html = admin_client.get("/reports/trainees/").content.decode()
    assert "Terry Trainee" not in html


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


def test_grid_tooltip_hides_draft_mentoring_partner_from_gp(gp_client, admin_user):
    # The mentoring-partner tooltip is built from the grid's own entry
    # queryset, which is the one place a draft companion pairing could leak
    # a trainee/trainer name to a GP before publish. Only the admin view was
    # covered before.
    from rota.services import entries as entries_svc
    PracticeSettings.load()
    ment = make_session_type("Mentoring", category="NON_CLINICAL")
    a, b = make_clinician("Alice Adams"), make_clinician("Terry Trainee")
    make_pattern(a)
    make_pattern(b)
    entries_svc.assign_pair(admin_user, MON, "AM", a, b, ment, published=False)
    html = gp_client.get(f"/rota/?week={MON}").content.decode()
    assert "with Terry Trainee" not in html
    assert "with Alice Adams" not in html


def test_accrual_window_aligns_expected_and_actual(admin_client, admin_user):
    """A rule met exactly over the measured weeks must not report as behind."""
    from datetime import date, timedelta

    from rota.models import CoverageRule
    from rota.services import entries as entries_svc
    from rota.services.fill.accrual import week_monday

    PracticeSettings.load()
    vas = make_session_type("Vas Clinic", fairness_tracked=True)
    CoverageRule.objects.create(
        session_type=vas, unit=CoverageRule.Unit.PER_SESSION,
        frequency=CoverageRule.Frequency.PER_WEEK, count=1,
        weekdays="0,1,2,3,4", priority=5)
    c = make_clinician("Alice Adams")
    wm_now = week_monday(date.today())
    # One entry in each of the four completed weeks `expected` measures
    # (the in-flight current week, offset 0, is deliberately excluded —
    # see test_a4_accrual_ignores_in_flight_week).
    for offset in (-28, -21, -14, -7):
        entries_svc.assign(admin_user, c, wm_now + timedelta(days=offset), "AM",
                           vas, published=True)
    html = admin_client.get("/reports/staffing/?weeks=1").content.decode()
    assert "behind target" not in html, "on-target rule reported as behind"


def test_accrual_hides_drafts_from_gps(gp_client, admin_client, admin_user):
    from datetime import date, timedelta

    from rota.models import CoverageRule
    from rota.services import entries as entries_svc
    from rota.services.fill.accrual import week_monday

    PracticeSettings.load()
    vas = make_session_type("Vas Clinic", fairness_tracked=True)
    CoverageRule.objects.create(
        session_type=vas, unit=CoverageRule.Unit.PER_SESSION,
        frequency=CoverageRule.Frequency.PER_WEEK, count=1,
        weekdays="0,1,2,3,4", priority=5)
    c = make_clinician("Alice Adams")
    wm_now = week_monday(date.today())
    # Four DRAFT entries covering the four completed weeks measured.
    for offset in (-28, -21, -14, -7):
        entries_svc.assign(admin_user, c, wm_now + timedelta(days=offset), "AM",
                           vas, published=False)
    admin_html = admin_client.get("/reports/staffing/?weeks=1").content.decode()
    gp_html = gp_client.get("/reports/staffing/?weeks=1").content.decode()
    assert "behind target" not in admin_html, "admin sees drafts, so on target"
    assert "behind target" in gp_html, "GP sees published only, so behind"


def test_a4_accrual_ignores_in_flight_week(admin_client, admin_user):
    """Full quota met in each of the last four *completed* weeks, with
    nothing yet delivered in the current, in-flight week, must not be
    reported behind — the current week hasn't happened yet, so it shouldn't
    count as fully due."""
    from datetime import date, timedelta

    from rota.models import CoverageRule
    from rota.services import entries as entries_svc
    from rota.services.fill.accrual import week_monday

    PracticeSettings.load()
    vas = make_session_type("Vas Clinic", fairness_tracked=True)
    CoverageRule.objects.create(
        session_type=vas, unit=CoverageRule.Unit.PER_SESSION,
        frequency=CoverageRule.Frequency.PER_WEEK, count=1,
        weekdays="0,1,2,3,4", priority=5)
    c = make_clinician("Alice Adams")
    wm_now = week_monday(date.today())
    for offset in (-28, -21, -14, -7):
        entries_svc.assign(admin_user, c, wm_now + timedelta(days=offset), "AM",
                           vas, published=True)
    # Deliberately nothing placed this week (offset 0).
    html = admin_client.get("/reports/staffing/?weeks=1").content.decode()
    assert "behind target" not in html, "in-flight week counted as fully due"


def test_trainee_report_query_count_does_not_grow_with_trainees(admin_client):
    """The point of the prefetched stage-rule mapping. This used to be done
    by monkeypatching profile.stage_rule with a lambda; the count is what
    that was protecting, so assert the count rather than the mechanism."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from tests.factories import make_clinician, make_trainee

    PracticeSettings.load()

    make_trainee(clinician=make_clinician("One Trainee", initials="O1"), stage="ST3")
    with CaptureQueriesContext(connection) as one:
        assert admin_client.get("/reports/trainees/").status_code == 200

    for i in range(6):
        make_trainee(clinician=make_clinician(f"Extra {i}", initials=f"X{i}"),
                     stage="ST2" if i % 2 else "ST3")
    with CaptureQueriesContext(connection) as many:
        assert admin_client.get("/reports/trainees/").status_code == 200

    assert len(many) == len(one), (
        f"query count grew from {len(one)} (1 trainee) to {len(many)} (7) — "
        f"something in the trainee report is per-profile again"
    )
