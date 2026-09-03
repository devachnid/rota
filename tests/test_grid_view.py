from datetime import timedelta

import pytest

from tests.factories import (MON, make_clinician, make_entry, make_group,
                             make_pattern, make_session_type)
from rota.models import ClosedDay, LocumRequirement, PracticeSettings

pytestmark = pytest.mark.django_db
URL = f"/rota/?week={MON}"


def test_requires_login(client):
    assert client.get("/rota/").status_code == 302


def test_gp_sees_published_not_drafts(gp_client):
    PracticeSettings.load()
    c = make_clinician()
    make_entry(c, part="AM", session_type=make_session_type("Routine", code="ROUT"))
    make_entry(c, part="PM", is_published=False,
               session_type=make_session_type("Duty", code="DUTY"))
    html = gp_client.get(URL).content.decode()
    assert "ROUT" in html and "DUTY" not in html


def test_admin_sees_drafts_hatched(admin_client):
    PracticeSettings.load()
    c = make_clinician()
    make_entry(c, part="AM", is_published=False,
               session_type=make_session_type("Duty", code="DUTY"))
    html = admin_client.get(URL).content.decode()
    assert "DUTY" in html and "draft" in html


def test_groups_render_in_order(admin_client):
    PracticeSettings.load()
    partners = make_group("Partner", display_order=1)
    make_clinician("Alice Adams", group=partners)
    make_clinician("Beth Brown", group=make_group("Salaried", display_order=2))
    html = admin_client.get(URL).content.decode()
    assert html.index("Partner") < html.index("Salaried")


def test_locum_requirements_render(admin_client):
    PracticeSettings.load()
    make_group("Locum", is_locum_group=True, display_order=99)
    LocumRequirement.objects.create(
        day=MON, part="AM", session_type=make_session_type("Routine"),
        status=LocumRequirement.Status.ADVERTISED,
    )
    html = admin_client.get(URL).content.decode()
    assert "Advertised" in html


def test_duty_day_renders_merged(admin_client):
    from rota.services import entries as entries_svc
    PracticeSettings.load()
    c = make_clinician()
    make_pattern(c)
    duty = make_session_type("Duty", code="DUTY", fairness_tracked=True)
    entries_svc.assign_full_day(None, c, MON, duty, published=True)
    html = admin_client.get(URL).content.decode()
    # day headers use <th colspan="2">; only a merged duty cell renders a <td> one
    assert '<td colspan="2"' in html


def test_week_param_snaps_to_monday(admin_client):
    PracticeSettings.load()
    c = make_clinician()
    make_entry(c, part="AM", session_type=make_session_type("Routine", code="ROUT"))
    wednesday = MON + timedelta(days=2)
    html = admin_client.get(f"/rota/?week={wednesday}").content.decode()
    assert "ROUT" in html


def test_closed_day_styled(admin_client):
    PracticeSettings.load()
    make_clinician()
    ClosedDay.objects.create(day=MON, reason="Bank holiday")
    html = admin_client.get(URL).content.decode()
    assert "closed" in html


def test_own_row_highlighted(gp_client, gp_user):
    PracticeSettings.load()
    c = make_clinician(user=gp_user)
    html = gp_client.get(URL).content.decode()
    assert "mine" in html


def test_swap_link_hidden_without_clinician_profile(admin_client):
    # admin_user (conftest) is a practice-manager-style account with no
    # linked Clinician; the view 403s on click, so the link must not render.
    PracticeSettings.load()
    html = admin_client.get(URL).content.decode()
    assert "Propose swap" not in html


def test_swap_link_shown_with_clinician_profile(gp_client, gp_user):
    PracticeSettings.load()
    make_clinician(user=gp_user)
    html = gp_client.get(URL).content.decode()
    assert "Propose swap" in html


def test_the_badge_tooltip_says_who_is_covered(admin_client):
    PracticeSettings.load()
    make_group("Locum", is_locum_group=True, display_order=99)
    covered = make_clinician("Cara Covered")
    LocumRequirement.objects.create(
        day=MON, part="AM", session_type=make_session_type("Routine"),
        status=LocumRequirement.Status.ADVERTISED, covering=covered,
        details="agency emailed",
    )
    html = admin_client.get(URL).content.decode()
    assert 'title="Covering Cara Covered — agency emailed"' in html
