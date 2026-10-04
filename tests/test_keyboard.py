"""The grid and its forms from the keyboard (review item 3A).

Before this a cell could only be edited with a mouse: an editable cell was a
<td hx-get> with no tabindex, and the modal took no focus, had no Escape and
gave nothing back when it closed. The browser half — Tab to a cell, Enter,
Tab trapped in the form, Escape back to the cell, save and land on the same
cell after the reload, Enter to tick — was driven key by key in headless
Chrome. What is pinned here is the markup and the script it depends on.
"""

import re
from pathlib import Path

import pytest

from rota.models import PracticeSettings
from tests.factories import MON, make_clinician, make_entry, make_pattern

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[1]
MODAL_JS = (ROOT / "static" / "js" / "modal.js").read_text()
GRID_JS = (ROOT / "static" / "js" / "grid.js").read_text()


def _grid(client, tick=False):
    PracticeSettings.load()
    return client.get(f"/rota/?week={MON}{'&tick=1' if tick else ''}").content.decode()


def _setup():
    c = make_clinician("Alice Adams")
    make_pattern(c)
    make_entry(c, part="AM")
    return c


# ---- the modal --------------------------------------------------------------

def test_the_modal_is_a_labelled_dialog(gp_client):
    PracticeSettings.load()
    html = gp_client.get("/me/").content.decode()
    assert '<div id="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">' in html
    assert html.count("js/modal.js") == 1


@pytest.mark.parametrize("template", [
    "rota/_cell_form.html", "rota/_daynote_form.html", "rota/_locum_form.html",
    "feedback/_form.html", "feedback/_sent.html"])
def test_everything_that_renders_into_it_names_it(template):
    """aria-labelledby points at #modal-title, so every form the modal can
    hold has to carry one — a dialog with a dangling label has none."""
    assert '<div class="modal-head" id="modal-title">' in (ROOT / "templates" / template).read_text()


def test_the_dialog_takes_focus_traps_tab_closes_on_escape_and_gives_focus_back():
    assert 'e.key === "Escape"' in MODAL_JS and 'modal.innerHTML = ""' in MODAL_JS
    assert 'e.key !== "Tab"' in MODAL_JS and "e.shiftKey" in MODAL_JS
    assert "[autofocus]" in MODAL_JS
    # A form back from the server asking to be saved again focuses Save.
    assert 'modal.querySelector(".alert") && modal.querySelector(\'button[type="submit"]\')' in MODAL_JS
    assert "opener.focus(" in MODAL_JS and "opener.isConnected" in MODAL_JS


# ---- the grid ----------------------------------------------------------------

def test_an_admins_cells_headings_and_badges_are_in_the_tab_order(admin_client):
    from tests.factories import make_group
    c = _setup()
    make_group("Locum GPs", is_locum_group=True, display_order=99)  # the Need row
    html = _grid(admin_client)
    assert f'hx-get="/rota/cell/{c.id}/{MON}/AM/" hx-target="#modal" tabindex="0"' in html
    assert re.search(r'hx-get="/rota/daynote/[^"]+/" hx-target="#modal" tabindex="0"', html)
    assert re.search(r'tabindex="0" role="button"\s+aria-label="Add a locum need, Mon', html)


def test_a_gp_has_nothing_to_tab_to_on_the_grid(gp_client):
    _setup()
    html = _grid(gp_client)
    table = html[html.index('<table class="table-grid"'):html.index("</table>")]
    assert 'tabindex="0"' not in table


def test_ticking_cells_are_in_the_tab_order_too(admin_client):
    _setup()
    assert re.search(r'hx-post="/rota/entered/"[^>]*tabindex="0"', _grid(admin_client, tick=True))


def test_enter_and_space_open_what_a_click_opens():
    assert 'e.key !== "Enter" && e.key !== " "' in GRID_JS
    assert "e.target.click()" in GRID_JS and "e.preventDefault()" in GRID_JS


def test_focus_comes_back_after_a_save_and_after_a_tick():
    """A save reloads the page and a tick replaces the row; either way a
    keyboard user would otherwise start again from the top."""
    assert 'sessionStorage.setItem(KEY, el.getAttribute("hx-get")' in GRID_JS
    assert "CSS.escape(wanted)" in GRID_JS
    assert 'td.getAttribute("hx-vals") === ticking' in GRID_JS


def test_a_cell_tabbed_to_is_scrolled_clear_of_the_sticky_column_and_header():
    assert "scrollPaddingLeft" in GRID_JS and "scrollPaddingTop" in GRID_JS


def test_the_focus_ring_is_drawn_inside_the_cell():
    from tests.test_css_cascade import rule
    assert rule(".table-grid [tabindex]:focus-visible").declarations["outline-offset"] == "-2px"
