import re
from datetime import date, timedelta

import pytest

from rota.models import LocumRequirement, SessionType
from tests.factories import (MON, make_absence, make_clinician, make_entry,
                             make_group, make_session_type)

pytestmark = pytest.mark.django_db


def _rows_html(html):
    """Just the table body. The Locum and Covering dropdowns list every
    locum / every ever-covered clinician regardless of the date range or
    the current filter, so a name check against the whole page would pass
    on a dropdown option alone — these tests care whether a *row* is
    listed."""
    return html[html.index("<tbody>"):html.index("</tbody>")]


@pytest.fixture
def world():
    """A locum group with Larry Locum in it, and two covered clinicians —
    Ann Able and Bob Baker — each in the default (non-locum) group."""
    locum_group = make_group("Locums", is_locum_group=True, display_order=99)
    larry = make_clinician("Larry Locum", group=locum_group)
    ann = make_clinician("Ann Able")
    bob = make_clinician("Bob Baker")
    rout = make_session_type("Routine", code="ROUT")

    def _book(day=MON, part="AM", locum=larry, covering=None,
             status=LocumRequirement.Status.BOOKED, with_entry=True):
        entry = None
        if with_entry:
            entry = make_entry(locum, day=day, part=part, session_type=rout,
                               is_published=True)
        return LocumRequirement.objects.create(
            day=day, part=part, session_type=rout, status=status,
            clinician=locum, covering=covering, rota_entry=entry,
        )

    return {"locum_group": locum_group, "larry": larry, "ann": ann,
            "bob": bob, "rout": rout, "book": _book}


def test_only_booked_requirements_are_listed(admin_client, world):
    other_statuses = [
        (LocumRequirement.Status.POSSIBLE, "Posy Possible"),
        (LocumRequirement.Status.APPROVED, "Andy Approved"),
        (LocumRequirement.Status.ADVERTISED, "Ada Advertised"),
    ]
    for status, name in other_statuses:
        c = make_clinician(name, group=world["locum_group"])
        LocumRequirement.objects.create(
            day=MON, part="AM", session_type=world["rout"], status=status,
            clinician=c,
        )
    world["book"](part="PM")  # the BOOKED one, Larry Locum

    html = admin_client.get(
        f"/reports/locums/?start={MON}&end={MON}").content.decode()
    rows = _rows_html(html)

    assert "Larry Locum" in rows
    for _status, name in other_statuses:
        assert name not in rows


def test_the_default_range_is_the_last_thirty_days(admin_client, world):
    today = date.today()
    old_locum = make_clinician("Ollie Old", group=world["locum_group"])
    LocumRequirement.objects.create(
        day=today - timedelta(days=31), part="AM", session_type=world["rout"],
        status=LocumRequirement.Status.BOOKED, clinician=old_locum,
    )
    world["book"](day=today - timedelta(days=29))

    html = admin_client.get("/reports/locums/").content.decode()
    rows = _rows_html(html)

    assert "Ollie Old" not in rows
    assert "Larry Locum" in rows


def test_a_malformed_date_falls_back_to_the_default(admin_client, world):
    today = date.today()
    world["book"](day=today - timedelta(days=29))

    resp = admin_client.get("/reports/locums/?start=junk")

    assert resp.status_code == 200
    assert "Larry Locum" in resp.content.decode()


def test_absence_comes_from_breathe_first(admin_client, world):
    make_absence(world["ann"], MON, kind="other", reason="Jury service")
    world["book"](covering=world["ann"])

    html = admin_client.get(
        f"/reports/locums/?start={MON}&end={MON}").content.decode()

    assert "Other leave: Jury service" in html


def test_absence_falls_back_to_an_absence_entry(admin_client, world):
    al = make_session_type("Annual Leave", code="AL",
                           category=SessionType.Category.ABSENCE)
    make_entry(world["bob"], day=MON, part="AM", session_type=al,
              is_published=True)
    world["book"](covering=world["bob"])

    html = admin_client.get(
        f"/reports/locums/?start={MON}&end={MON}").content.decode()

    assert "Annual Leave" in html


def test_a_draft_absence_entry_counts_only_for_admins(admin_client, gp_client,
                                                       world):
    al = make_session_type("Annual Leave", code="AL",
                           category=SessionType.Category.ABSENCE)
    make_entry(world["bob"], day=MON, part="AM", session_type=al,
              is_published=False)
    world["book"](covering=world["bob"])

    admin_html = admin_client.get(
        f"/reports/locums/?start={MON}&end={MON}").content.decode()
    gp_html = gp_client.get(
        f"/reports/locums/?start={MON}&end={MON}").content.decode()

    assert "Annual Leave" in admin_html
    assert "No absence recorded" in gp_html
    assert "Annual Leave" not in gp_html


def test_no_absence_recorded_and_no_covering(admin_client, world):
    other = make_clinician("Nora Nolocum", group=world["locum_group"])
    world["book"](covering=world["ann"])                 # nothing recorded
    world["book"](part="PM", locum=other, covering=None)  # no covering at all

    html = admin_client.get(
        f"/reports/locums/?start={MON}&end={MON}").content.decode()

    assert "No absence recorded" in html
    # Nora's row: Locum name, then Covering "—", then Absence "—" — the two
    # dashes must not be confused with "No absence recorded".
    assert re.search(r"Nora Nolocum</td>\s*<td>—</td>\s*<td>—</td>", html), (
        "a booking with no covering clinician should show em-dashes for both "
        "the Covering and Absence cells, not 'No absence recorded'"
    )


def test_each_filter_narrows_and_they_combine(admin_client, world):
    lena = make_clinician("Lena Locum2", group=world["locum_group"])
    make_absence(world["ann"], MON, kind="holiday")
    al = make_session_type("Annual Leave", code="AL",
                           category=SessionType.Category.ABSENCE)
    make_entry(world["bob"], day=MON, part="AM", session_type=al,
              is_published=True)

    world["book"](day=MON, part="PM", locum=world["larry"], covering=world["ann"])
    world["book"](day=MON, part="AM", locum=lena, covering=world["bob"])

    base = f"/reports/locums/?start={MON}&end={MON}"

    html_locum = admin_client.get(
        f"{base}&locum={world['larry'].id}").content.decode()
    rows_locum = _rows_html(html_locum)
    assert "Larry Locum" in rows_locum and "Lena Locum2" not in rows_locum

    html_covering = admin_client.get(
        f"{base}&covering={world['bob'].id}").content.decode()
    rows_covering = _rows_html(html_covering)
    assert "Bob Baker" in rows_covering
    assert "Ann Able" not in rows_covering
    # the covering select keeps its choice selected
    assert f'value="{world["bob"].id}" selected' in html_covering

    html_absence = admin_client.get(f"{base}&absence=Holiday").content.decode()
    rows_absence = _rows_html(html_absence)
    assert "Larry Locum" in rows_absence and "Lena Locum2" not in rows_absence
    # the dropdown still offers both labels present in the date range, even
    # though the rows are now filtered down to one of them
    assert "Holiday" in html_absence
    assert "Annual Leave" in html_absence

    html_combo = admin_client.get(
        f"{base}&locum={world['larry'].id}&absence=Holiday").content.decode()
    rows_combo = _rows_html(html_combo)
    assert "Larry Locum" in rows_combo and "Lena Locum2" not in rows_combo


def test_a_cleared_session_still_counts_as_a_booking(admin_client, world):
    booking = world["book"](with_entry=False)
    assert booking.rota_entry_id is None

    html = admin_client.get(
        f"/reports/locums/?start={MON}&end={MON}").content.decode()

    assert "Larry Locum" in html
    assert "(session cleared)" in html


def test_the_nav_links_all_four_reports(admin_client):
    urls = ["/reports/fairness/", "/reports/staffing/",
            "/reports/trainees/", "/reports/locums/"]
    for url in urls:
        html = admin_client.get(url).content.decode()
        for other in urls:
            if other != url:
                assert f'href="{other}"' in html, (
                    f"{url} does not link to {other}"
                )


def test_the_report_does_not_query_per_booking(admin_client, world):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    def add(n, tag):
        for i in range(n):
            locum = make_clinician(f"Locum {tag}{i}", group=world["locum_group"],
                                   initials=f"L{tag}{i}")
            covered = make_clinician(f"Covered {tag}{i}", initials=f"C{tag}{i}")
            make_absence(covered, MON, kind="holiday")
            world["book"](day=MON, part="AM", locum=locum, covering=covered)

    def queries():
        with CaptureQueriesContext(connection) as ctx:
            resp = admin_client.get(f"/reports/locums/?start={MON}&end={MON}")
        assert resp.status_code == 200
        return len(ctx)

    add(2, "a")
    queries()  # warm up: session and template lookups
    baseline = queries()
    assert "Holiday" in admin_client.get(
        f"/reports/locums/?start={MON}&end={MON}").content.decode(), (
        "the absence labels must actually be rendering for this to measure them"
    )

    add(8, "b")
    assert queries() == baseline, (
        "the report issues more queries with more bookings — something is "
        "asking per row"
    )
