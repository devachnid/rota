"""Ticking mode: an admin-only URL flag under which clicking a chip marks
the session as entered in the clinical system, in place, no form. The
mark is struck through for admins and invisible to everyone else."""

from datetime import timedelta

import pytest

from rota.models import PracticeSettings, RotaEntry
from rota.services import entries as entries_svc
from tests.factories import MON, make_clinician, make_entry, make_pattern, make_session_type

pytestmark = pytest.mark.django_db
TUE = MON + timedelta(days=1)


def _setup():
    PracticeSettings.load()
    c = make_clinician()
    make_pattern(c)
    rout = make_session_type("Routine", code="ROUT")
    e = make_entry(c, day=TUE, part="AM", session_type=rout)
    return c, e


def test_the_toolbar_offers_ticking_mode_to_an_admin_only(admin_client, gp_client):
    _setup()
    on = admin_client.get(f"/rota/?week={MON}").content.decode()
    assert f'href="?week={MON}&amp;tick=1"' in on or f'href="?week={MON}&tick=1"' in on
    assert 'aria-pressed="false"' in on
    assert "Ticking mode" not in gp_client.get(f"/rota/?week={MON}").content.decode()


def test_the_flag_is_ignored_for_a_gp(gp_client):
    _setup()
    html = gp_client.get(f"/rota/?week={MON}&tick=1").content.decode()
    assert "is-ticking" not in html and "/rota/entered/" not in html


def test_in_ticking_mode_cells_with_entries_post_and_empty_cells_do_nothing(admin_client):
    c, e = _setup()
    html = admin_client.get(f"/rota/?week={MON}&tick=1").content.decode()
    assert 'class="page-grid is-ticking"' in html
    assert 'aria-pressed="true"' in html
    assert "click a session to mark it entered" in html
    i = html.index(f'"day": "{TUE}", "part": "AM"')
    td = html[html.rindex("<td", 0, i):i + 200]
    assert 'hx-post="/rota/entered/"' in td and 'hx-target="closest tr"' in td
    assert "hx-get" not in td
    assert f'"week": "{MON}"' in td
    assert f'hx-get="/rota/cell/{c.id}/{MON}/AM/"' not in html
    assert "/rota/cell/" not in html


def test_the_earlier_later_and_today_links_carry_the_flag(admin_client):
    _setup()
    html = admin_client.get(f"/rota/?week={MON}&tick=1").content.decode()
    assert f'href="?week={MON - timedelta(days=28)}&amp;tick=1"' in html \
        or f'href="?week={MON - timedelta(days=28)}&tick=1"' in html
    assert 'name="tick" value="1"' in html            # the Go form


def test_posting_toggles_and_returns_the_row(admin_client, admin_user):
    c, e = _setup()
    resp = admin_client.post("/rota/entered/", {
        "clinician_id": c.id, "day": str(TUE), "part": "AM", "week": str(MON)})
    assert resp.status_code == 200
    html = resp.content.decode()
    assert html.lstrip().startswith("<tr") and html.count("<tr") == 1
    assert "is-entered" in html and "Entered " in html and "by admin@example.com" in html
    e.refresh_from_db()
    assert e.entered_by == admin_user
    admin_client.post("/rota/entered/", {
        "clinician_id": c.id, "day": str(TUE), "part": "AM", "week": str(MON)})
    e.refresh_from_db()
    assert e.entered_at is None


def test_a_whole_day_post_marks_both_halves_and_unmarks_when_all_marked(admin_client, admin_user):
    PracticeSettings.load()
    c = make_clinician()
    make_pattern(c)
    duty = make_session_type("Duty", code="DUTY")
    entries_svc.assign_full_day(admin_user, c, TUE, duty, published=True)
    admin_client.post("/rota/entered/", {
        "clinician_id": c.id, "day": str(TUE), "part": "DAY", "week": str(MON)})
    assert RotaEntry.objects.filter(day=TUE, entered_at__isnull=False).count() == 2
    entries_svc.set_entered(admin_user, RotaEntry.objects.get(day=TUE, part="PM"), False)
    admin_client.post("/rota/entered/", {
        "clinician_id": c.id, "day": str(TUE), "part": "DAY", "week": str(MON)})
    assert RotaEntry.objects.filter(day=TUE, entered_at__isnull=False).count() == 2, (
        "one half unmarked means the day is not all done: mark, don't unmark")


def test_the_endpoint_is_admin_only_and_post_only(gp_client, admin_client):
    c, e = _setup()
    assert gp_client.post("/rota/entered/", {
        "clinician_id": c.id, "day": str(TUE), "part": "AM"}).status_code in (302, 403)
    assert admin_client.get("/rota/entered/").status_code == 405


def test_the_strike_shows_for_an_admin_and_not_a_gp(admin_client, gp_client, admin_user):
    c, e = _setup()
    entries_svc.set_entered(admin_user, e, True)
    admin_html = admin_client.get(f"/rota/?week={MON}").content.decode()
    gp_html = gp_client.get(f"/rota/?week={MON}").content.decode()
    assert "is-entered" in admin_html and "Entered " in admin_html
    assert "is-entered" not in gp_html and "Entered " not in gp_html
