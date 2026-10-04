"""Paper. A GP rota gets printed and pinned up, and there was no print
stylesheet: a printout was the nav, the tab bar and a pane clipped to one
screen of an eight-week table. print.css is loaded for print only; the
browser half — what lands on the page — was checked by printing the grid,
the day view and My Schedule to PDF in headless Chrome.
"""

import re
from datetime import timedelta
from pathlib import Path

import pytest

from rota.models import PracticeSettings
from tests.factories import MON, make_clinician, make_entry, make_pattern

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[1]
PRINT = (ROOT / "static" / "css" / "print.css").read_text()
THEME = (ROOT / "static" / "js" / "theme.js").read_text()


def _rule(selector_text):
    body = PRINT[PRINT.index(selector_text):]
    return body[body.index("{") + 1:body.index("}")]


def test_it_is_loaded_for_print_and_nothing_else(client):
    html = client.get("/accounts/login/").content.decode()
    assert re.search(r'<link rel="stylesheet" href="[^"]*print\.css" media="print">', html)


def test_the_screen_chrome_stays_off_paper():
    hidden = PRINT[:PRINT.index("{", PRINT.index(".nav,"))]
    for selector in (".nav,", ".tabbar,", ".flashes,", "#modal,", ".toolbar,", ".form-actions,"):
        assert selector in hidden, selector


def test_the_grids_warnings_stay_off_paper_but_the_reports_do_not():
    """A gap list on the wall rota is a to-do pinned in public; the staffing
    report's issues are the report."""
    assert ".page-grid .alert," in PRINT
    assert re.search(r"^\.alert[ ,{]", PRINT, re.M) is None


def test_a_chip_keeps_its_colour_on_paper():
    assert "print-color-adjust: exact" in _rule(".chip,\n.badge {")


def test_the_grid_asks_for_a_landscape_page():
    assert "@page grid { size: landscape" in PRINT
    assert ".page-grid .main { page: grid; }" in PRINT


def test_the_grid_is_a_table_on_paper_not_a_pane():
    assert "overflow: visible" in _rule(".grid-wrap {")
    assert "height: auto" in _rule("body.page-grid {")


def test_only_the_anchor_week_is_printed():
    assert ".table-grid tr:not(.grid-group) > :not(.grid-clin):not(.anchor-week)" in PRINT
    assert "display: none" in _rule(".table-grid tr:not(.grid-group) > :not(.grid-clin):not(.anchor-week) {")


def test_the_grid_marks_exactly_the_anchor_weeks_cells(admin_client):
    """Five open days: ten session columns in each of the day-header row's
    ten halves, and every clinician cell of that week — and none of the
    seven other weeks on screen."""
    PracticeSettings.load()
    c = make_clinician("Alice Adams")
    make_pattern(c)
    make_entry(c, day=MON, part="AM")
    make_entry(c, day=MON + timedelta(days=7), part="AM")  # next week: not printed
    html = admin_client.get(f"/rota/?week={MON}").content.decode()
    days = re.findall(r'<th colspan="2"[^>]*class="grid-day[^"]*anchor-week', html)
    parts = re.findall(r'class="grid-part[^"]*anchor-week', html)
    assert len(days) == 5 and len(parts) == 10
    row = html[html.index('title="Alice Adams"'):]
    row = row[:row.index("</tr>")]
    cells = re.findall(r"<td[^>]*>", row)
    assert sum("anchor-week" in td for td in cells) == 10
    assert len(cells) == 80  # eight weeks on screen


def test_the_printout_says_which_week(gp_client):
    PracticeSettings.load()
    html = gp_client.get(f"/rota/?week={MON}").content.decode()
    assert f'<h1 class="print-only">Rota — week of {MON:%-d %B %Y}</h1>' in html


def test_printing_uses_the_light_palette_and_puts_the_theme_back():
    """Light text on white paper is what a dark theme prints as."""
    assert '"beforeprint"' in THEME and '"afterprint"' in THEME
    before = THEME[THEME.index('"beforeprint"'):THEME.index('"afterprint"')]
    assert 'setAttribute("data-theme", "light")' in before
    after = THEME[THEME.index('"afterprint"'):]
    assert 'removeAttribute("data-theme")' in after, "system stays system"


def test_a_second_beforeprint_does_not_overwrite_the_theme_to_restore():
    """Seen printing to PDF in headless Chrome: beforeprint arrived twice,
    the second recorded "light", and the dark theme never came back."""
    before = THEME[THEME.index('"beforeprint"'):THEME.index('"afterprint"')]
    guard = before.index("if (!printing)")
    assert guard < before.index("shown = ") < before.index('setAttribute("data-theme", "light")')


def test_the_group_labels_stop_spanning_eight_weeks_on_paper():
    """Found by printing: each label row is one cell spanning every column
    on screen, so it kept seventy empty columns in a one-week table and
    left each session ~11px of an A4 page."""
    rule = _rule(".table-grid .grid-group td {")
    assert "display: block" in rule
