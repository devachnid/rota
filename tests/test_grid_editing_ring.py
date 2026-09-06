"""The cell whose form is open is ringed. The page loads the script, the
script wires the two moments (a grid click opening the modal; the modal
emptying) to one class, and the stylesheet gives that class a ring."""

from pathlib import Path

import pytest

from tests.test_css_cascade import rule

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.django_db


def test_the_week_page_loads_the_grid_script(admin_client):
    from rota.models import PracticeSettings
    PracticeSettings.load()
    html = admin_client.get("/rota/").content.decode()
    assert 'src="/static/js/grid.js"' in html and "defer" in html.split("js/grid.js")[1][:40]


def test_the_script_sets_the_class_on_open_and_clears_it_on_close():
    js = (ROOT / "static/js/grid.js").read_text()
    assert "htmx:beforeRequest" in js and 'closest(".table-grid")' in js
    assert 'closest("td, th")' in js and 'classList.add("is-editing")' in js
    assert "MutationObserver" in js and "childElementCount" in js


def test_the_ring_is_an_inset_accent_on_cells_and_headers():
    for selector in (".table-grid td.is-editing", ".table-grid th.is-editing"):
        shadow = rule(selector).declarations.get("box-shadow", "")
        assert shadow.startswith("inset") and "var(--accent)" in shadow, (selector, shadow)
