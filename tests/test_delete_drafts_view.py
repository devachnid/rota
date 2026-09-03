"""The Delete-drafts card on the fill screen. Nothing is deleted without
the second click — the spec's preview rule for destructive actions."""

import re
from datetime import timedelta

import pytest

from rota.models import RotaEntry
from tests.factories import MON, make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db

URL = "/rota/drafts/delete/"
FRI = MON + timedelta(days=4)


@pytest.fixture
def drafts():
    rout = make_session_type("Routine", code="ROUT")
    c = make_clinician()
    make_entry(c, day=MON, part="AM", session_type=rout)                       # published
    make_entry(c, day=MON, part="PM", session_type=rout, is_published=False,
               manually_set=False)
    make_entry(c, day=FRI, part="AM", session_type=rout, is_published=False)   # hand-placed
    make_entry(c, day=FRI + timedelta(days=3), part="AM", session_type=rout,
               is_published=False, manually_set=False)


def test_the_card_is_on_the_fill_screen(admin_client):
    html = admin_client.get("/rota/fill/").content.decode()
    assert "Delete drafts" in html
    assert f'action="{URL}"' in html


def test_a_gp_cannot_reach_it(gp_client):
    assert gp_client.post(URL, {"scope": "all", "range": "all"}).status_code == 403


def test_get_is_not_allowed(admin_client):
    assert admin_client.get(URL).status_code == 405


def test_the_first_post_previews_and_deletes_nothing(drafts, admin_client):
    resp = admin_client.post(URL, {"scope": "all", "range": "dates",
                                   "start": MON.isoformat(), "end": FRI.isoformat()})
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "2 drafts" in html and "1 placed by hand" in html
    assert 'name="confirm"' in html
    assert RotaEntry.objects.filter(is_published=False).count() == 3


def test_the_confirmed_post_deletes_flashes_and_returns_to_the_fill_screen(drafts, admin_client):
    resp = admin_client.post(URL, {"scope": "all", "range": "dates",
                                   "start": MON.isoformat(), "end": FRI.isoformat(),
                                   "confirm": "1"})
    assert resp.status_code == 302 and resp["Location"] == "/rota/fill/"
    assert RotaEntry.objects.filter(is_published=False).count() == 1
    assert RotaEntry.objects.filter(is_published=True).count() == 1
    followed = admin_client.get("/rota/fill/").content.decode()
    assert "Deleted 2 drafts." in followed


def test_fill_scope_over_all_dates(drafts, admin_client):
    admin_client.post(URL, {"scope": "fill", "range": "all", "confirm": "1"})
    left = RotaEntry.objects.filter(is_published=False)
    assert left.count() == 1 and left.get().manually_set


def test_a_bad_date_is_a_400(admin_client):
    assert admin_client.post(URL, {"scope": "all", "range": "dates",
                                   "start": "junk", "end": "junk"}).status_code == 400


def test_an_end_before_the_start_is_a_400(admin_client):
    resp = admin_client.post(URL, {"scope": "all", "range": "dates",
                                   "start": FRI.isoformat(), "end": MON.isoformat()})
    assert resp.status_code == 400
    assert b"before" in resp.content


def test_the_confirm_form_carries_the_previewed_scope_and_the_screen_shows_it(drafts, admin_client):
    resp = admin_client.post(URL, {"scope": "fill", "range": "all"})
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "only the fill engine's own drafts" in html

    scope_block = html[html.index('name="scope"'):html.index('name="range"')]
    assert 'value="fill" checked' in scope_block
    assert 'value="all" checked' not in scope_block

    last_form_start = html.rindex('<form method="post" action="/rota/drafts/delete/">')
    confirm_form = html[last_form_start:html.index("</form>", last_form_start)]
    hidden = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', confirm_form))

    resp2 = admin_client.post(URL, hidden)
    assert resp2.status_code == 302 and resp2["Location"] == "/rota/fill/"
    assert RotaEntry.objects.filter(day=FRI, part="AM", manually_set=True).exists()
    assert not RotaEntry.objects.filter(is_published=False, manually_set=False).exists()


def test_a_confirmed_range_with_no_dates_is_refused(drafts, admin_client):
    resp = admin_client.post(URL, {"scope": "all", "range": "dates", "confirm": "1"})
    assert resp.status_code == 400
    assert RotaEntry.objects.filter(is_published=False).count() == 3


def test_an_unknown_scope_is_a_400_not_the_broadest_reading(drafts, admin_client):
    resp = admin_client.post(URL, {"scope": "junk", "range": "all", "confirm": "1"})
    assert resp.status_code == 400
    assert RotaEntry.objects.filter(is_published=False).count() == 3


def test_an_unknown_range_is_a_400_not_the_broadest_reading(drafts, admin_client):
    resp = admin_client.post(URL, {"scope": "all", "range": "junk", "confirm": "1"})
    assert resp.status_code == 400
    assert RotaEntry.objects.filter(is_published=False).count() == 3
