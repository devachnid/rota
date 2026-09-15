"""The grid shows a run of weeks — one before the anchor week, six after —
in one table, with a header cell per week, a heavier rule at each week
boundary, today marked, and each week's Publish in its own header."""

from datetime import date, timedelta

import pytest

from rota.models import PracticeSettings
from rota.services import entries as entries_svc
from rota.services import grid as grid_svc
from tests.factories import (MON, make_absence, make_clinician, make_entry,
                             make_pattern, make_session_type)

pytestmark = pytest.mark.django_db


def _page(client, anchor=MON):
    PracticeSettings.load()
    return client.get(f"/rota/?week={anchor}").content.decode()


def test_parse_anchor_snaps_to_monday_and_falls_back_to_today():
    assert grid_svc.parse_anchor("2026-07-22", today=date(2026, 1, 1)) == MON
    assert grid_svc.parse_anchor("", today=date(2026, 7, 23)) == MON
    assert grid_svc.parse_anchor("nonsense", today=date(2026, 7, 23)) == MON
    assert grid_svc.parse_anchor(None, today=date(2026, 7, 23)) == MON


def test_the_window_spans_one_week_back_and_six_forward(admin_client):
    html = _page(admin_client)
    first = MON - timedelta(days=7)
    last = MON + timedelta(days=6 * 7 + 4)
    assert f'hx-get="/rota/daynote/{first}/"' in html
    assert f'hx-get="/rota/daynote/{last}/"' in html
    assert f'hx-get="/rota/daynote/{first - timedelta(days=3)}/"' not in html
    assert f'hx-get="/rota/daynote/{last + timedelta(days=3)}/"' not in html
    assert f"Weeks of {first:%-d %b} – {last:%-d %b %Y}" in html
    assert html.count('class="grid-day') == 40


def test_earlier_and_later_step_four_weeks(admin_client):
    html = _page(admin_client)
    assert f'href="?week={MON - timedelta(days=28)}"' in html
    assert f'href="?week={MON + timedelta(days=28)}"' in html


def test_the_publish_row_has_a_cell_per_week_spanning_its_open_days(admin_client):
    make_entry(make_clinician(), day=MON, part="AM", is_published=False,
               session_type=make_session_type("Duty", code="DUTY"))
    html = _page(admin_client)
    assert html.count('<th colspan="10" scope="colgroup" class="grid-week') == 8


def test_no_week_row_at_all_when_nothing_needs_publishing(admin_client):
    """The "Week of" label duplicated the dates underneath, and an
    admin's row of eight empty cells was just height. The row exists only
    while a week has drafts to publish or a week ceiling warning."""
    html = _page(admin_client)
    assert "grid-week" not in html and "Week of" not in html


def test_the_anchor_week_is_marked(admin_client):
    html = _page(admin_client)
    assert html.count("is-anchor") == 1
    start = html.index("is-anchor")
    assert f'hx-get="/rota/daynote/{MON}/"' in html[start:start + 160]


def test_week_start_lands_on_mondays_only(admin_client):
    c = make_clinician()
    make_pattern(c)
    html = _page(admin_client)
    for offset, expected in ((0, True), (1, False), (7, True), (-7, True)):
        d = MON + timedelta(days=offset)
        i = html.index(f'hx-get="/rota/cell/{c.id}/{d}/AM/"')
        td = html[html.rindex("<td", 0, i):i]
        assert ("week-start" in td) is expected, (d, td)


def test_today_is_marked_when_inside_the_window(admin_client, monkeypatch):
    monkeypatch.setattr(grid_svc, "_today", lambda: MON + timedelta(days=2))
    c = make_clinician()
    make_pattern(c)
    html = _page(admin_client)
    wed = MON + timedelta(days=2)
    assert "grid-day is-today" in html
    assert html.count('class="grid-part is-today"') == 2
    # The header alone marks today: per-cell edges drew a bar at each side
    # of the AM/PM pair and a double bar between them.
    i = html.index(f'hx-get="/rota/cell/{c.id}/{wed}/AM/"')
    assert "is-today" not in html[html.rindex("<td", 0, i):i]
    assert 'id="grid-today"' in html and 'data-scroll="1"' in html


def test_today_outside_the_window_is_a_plain_link(admin_client, monkeypatch):
    far = MON + timedelta(days=365)
    monkeypatch.setattr(grid_svc, "_today", lambda: far)
    html = _page(admin_client)
    assert "is-today" not in html
    assert f'href="?week={far}" class="btn" id="grid-today"' in html
    assert 'data-scroll="1"' not in html


def test_publish_sits_in_the_week_header_only_when_there_are_drafts(admin_client):
    c = make_clinician()
    duty = make_session_type("Duty", code="DUTY")
    make_entry(c, day=MON + timedelta(days=7), part="AM", is_published=False,
               session_type=duty)
    html = _page(admin_client)
    assert html.count('hx-post="/rota/publish/"') == 1
    form_at = html.index('hx-post="/rota/publish/"')
    form = html[form_at:form_at + 400]
    assert f'name="start" value="{MON + timedelta(days=7)}"' in form
    assert f'name="end" value="{MON + timedelta(days=11)}"' in form
    assert f"Publish week of {MON + timedelta(days=7):%-d %b} · 1 draft" in form
    assert "Publish week" not in html.split('<div class="grid-wrap">')[0]


def test_a_gp_sees_no_publish_and_no_drafts(gp_client):
    c = make_clinician()
    make_entry(c, day=MON, part="AM", is_published=False,
               session_type=make_session_type("Duty", code="DUTY"))
    html = _page(gp_client)
    assert "/rota/publish/" not in html and "DUTY" not in html


def test_the_week_ceiling_warning_sits_in_its_week_header(admin_client):
    larc = make_session_type("LARC", code="LARC", max_per_week=1)
    c = make_clinician()
    make_entry(c, day=MON, part="AM", session_type=larc)
    make_entry(c, day=MON + timedelta(days=1), part="AM", session_type=larc)
    html = _page(admin_client)
    week_cell = html.index(f'data-monday="{MON}"')
    next_cell = html.index(f'data-monday="{MON + timedelta(days=7)}"')
    assert "Too many LARC this week" in html[week_cell:next_cell]


def test_the_table_declares_its_column_count_and_start(admin_client):
    html = _page(admin_client)
    assert 'style="--cols: 80"' in html
    assert f'data-start="{MON - timedelta(days=7)}"' in html


def test_query_count_does_not_grow_with_weeks_of_entries(admin_client, admin_user):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    PracticeSettings.load()
    c = make_clinician()
    make_pattern(c)
    duty = make_session_type("Duty", code="DUTY")
    # A Breathe clash too, so _breathe_conflicts runs through the bundle
    # like every other warning source this test guards.
    make_absence(c, MON)
    entry = make_entry(c, day=MON, part="AM", session_type=duty)
    entries_svc.set_entered(admin_user, entry, True)
    with CaptureQueriesContext(connection) as one_week:
        admin_client.get(f"/rota/?week={MON}")
    for w in range(-1, 7):
        for d in range(5):
            if (w, d) != (0, 0):
                entry = make_entry(c, day=MON + timedelta(days=7 * w + d), part="AM",
                                   session_type=duty)
                entries_svc.set_entered(admin_user, entry, True)
    with CaptureQueriesContext(connection) as eight_weeks:
        admin_client.get(f"/rota/?week={MON}")
    assert len(eight_weeks) == len(one_week), (
        f"{len(one_week)} queries with one week of entries, "
        f"{len(eight_weeks)} with eight")
    assert len(one_week) <= 30, len(one_week)


def _day_cell(html, day):
    start = html.index(f'hx-get="/rota/daynote/{day}/"')
    return html[html.rindex("<th", 0, start):html.index("</th>", start)]


def test_a_day_header_shows_two_warnings_and_counts_the_rest(admin_client):
    """A table row is as tall as its tallest cell, and the sticky header
    row now spans forty days. An unfilled week at the far end carried a
    dozen warning lines per day, so the whole header grew to 435px and
    swallowed the pane. Two lines and a count keep the height bounded;
    the full list stays in the cell's tooltip."""
    from rota.models import CoverageRule
    PracticeSettings.objects.update_or_create(
        pk=1, defaults={"min_clinical_per_session": 0})
    for name in ("Duty", "Urgent", "Routine"):
        CoverageRule.objects.create(session_type=make_session_type(name, code=name[:4].upper()))
    cell = _day_cell(_page(admin_client), MON)
    assert cell.count('<div class="warn">') == 2
    assert "+4 more" in cell
    assert 'title="' in cell
    for name in ("Duty", "Urgent", "Routine"):
        for part in ("AM", "PM"):
            assert f"No {name} cover ({part})" in cell


def test_a_day_with_two_warnings_shows_both_and_no_count(admin_client):
    from rota.models import CoverageRule
    PracticeSettings.objects.update_or_create(
        pk=1, defaults={"min_clinical_per_session": 0})
    CoverageRule.objects.create(session_type=make_session_type("Duty", code="DUTY"))
    cell = _day_cell(_page(admin_client), MON)
    assert cell.count('<div class="warn">') == 2
    assert "more" not in cell
