"""A day whose two halves would show the same chip is drawn as one, and its
form edits the whole day unless a half is chosen — the split."""

import re

import pytest

from rota.models import PracticeSettings, RotaEntry
from tests.factories import (MON, make_clinician, make_entry, make_pattern,
                             make_session_type, make_site)

pytestmark = pytest.mark.django_db
URL = f"/rota/?week={MON}"


def _cells(html, clinician):
    """The <td> tags on the clinician's row, as (attributes) strings."""
    row = re.search(rf'<th class="grid-clin"[^>]*>{clinician.initials}</th>(.*?)</tr>',
                    html, re.S).group(1)
    return re.findall(r"<td ([^>]*)>", row)


def _setup(**pm_kw):
    PracticeSettings.load()
    c = make_clinician()
    make_pattern(c)
    rout = make_session_type("Routine", code="ROUT")
    make_entry(c, part="AM", session_type=rout)
    make_entry(c, part="PM", session_type=pm_kw.pop("session_type", rout), **pm_kw)
    return c


def test_matching_halves_are_one_chip_without_an_allocation_group(admin_client):
    c = _setup()
    assert not RotaEntry.objects.exclude(allocation_group=None).exists()
    first = _cells(admin_client.get(URL).content.decode(), c)[0]
    assert 'colspan="2"' in first
    # ...and its form is the whole day's.
    assert f'hx-get="/rota/cell/{c.id}/{MON}/DAY/"' in first


@pytest.mark.parametrize("difference", ["type", "site", "draft"])
def test_halves_that_would_look_different_stay_two_chips(admin_client, difference):
    kw = {"type": {"session_type": make_session_type("Duty", code="DUTY")},
          "site": {"site": make_site()},
          "draft": {"is_published": False}}[difference]
    c = _setup(**kw)
    monday = _cells(admin_client.get(URL).content.decode(), c)[:2]
    assert all('colspan' not in td for td in monday)
    assert f'hx-get="/rota/cell/{c.id}/{MON}/AM/"' in monday[0]
    assert f'hx-get="/rota/cell/{c.id}/{MON}/PM/"' in monday[1]


def test_differing_notes_do_not_split_the_chip_but_both_are_told(admin_client):
    c = _setup(note="leaves at 5")
    RotaEntry.objects.filter(part="AM").update(note="late start")
    html = admin_client.get(URL).content.decode()
    first = _cells(html, c)[0]
    assert 'colspan="2"' in first
    assert "AM: late start — PM: leaves at 5" in first
    assert "has-note" in html


def test_a_note_on_one_half_only_is_the_chip_note(admin_client):
    c = _setup(note="leaves at 5")
    first = _cells(admin_client.get(URL).content.decode(), c)[0]
    assert 'colspan="2"' in first and "leaves at 5" in first and "AM:" not in first


def test_the_whole_day_form_opens_on_whole_day_and_says_so(admin_client):
    c = _setup()
    html = admin_client.get(f"/rota/cell/{c.id}/{MON}/DAY/").content.decode()
    assert "all day" in html
    assert 'value="DAY" checked' in html
    assert 'value="AM" checked' not in html
    # A single cell's form opens on the half that was clicked.
    html = admin_client.get(f"/rota/cell/{c.id}/{MON}/PM/").content.decode()
    assert 'value="PM" checked' in html and 'value="DAY" checked' not in html


def test_an_unknown_part_is_a_bad_request(admin_client):
    c = _setup()
    assert admin_client.get(f"/rota/cell/{c.id}/{MON}/EVE/").status_code == 400


def test_saving_one_half_splits_the_day(admin_client):
    c = _setup()
    duty = make_session_type("Duty", code="DUTY")
    resp = admin_client.post("/rota/assign/", {
        "clinician_id": c.id, "day": MON.isoformat(), "part": "PM",
        "session_type_id": duty.id, "note": ""})
    assert resp.status_code == 204
    by_part = {e.part: e for e in RotaEntry.objects.filter(day=MON)}
    assert by_part["AM"].session_type.code == "ROUT"
    assert by_part["PM"].session_type.code == "DUTY"
    monday = _cells(admin_client.get(URL).content.decode(), c)[:2]
    assert all("colspan" not in td for td in monday)


def test_saving_the_whole_day_writes_both_halves(admin_client):
    c = _setup(session_type=make_session_type("Duty", code="DUTY"))
    rout = make_session_type("Routine", code="ROUT")
    admin_client.post("/rota/assign/", {
        "clinician_id": c.id, "day": MON.isoformat(), "part": "DAY",
        "session_type_id": rout.id, "note": "both"})
    entries = list(RotaEntry.objects.filter(day=MON))
    assert {e.session_type.code for e in entries} == {"ROUT"}
    assert {e.note for e in entries} == {"both"}
    assert len({e.allocation_group for e in entries}) == 1 and entries[0].allocation_group


def test_clearing_the_whole_day_clears_both_halves(admin_client):
    c = _setup()
    resp = admin_client.post("/rota/clear/", {
        "clinician_id": c.id, "day": MON.isoformat(), "part": "DAY"})
    assert resp.status_code == 204 and not RotaEntry.objects.exists()


def test_clearing_one_half_keeps_the_other(admin_client):
    c = _setup()
    admin_client.post("/rota/clear/", {
        "clinician_id": c.id, "day": MON.isoformat(), "part": "AM"})
    assert list(RotaEntry.objects.values_list("part", flat=True)) == ["PM"]
