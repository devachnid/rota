"""The pane scrolls to the anchor week on load, remembers where it was
across the full-page refresh every cell save triggers, and the Today
button scrolls rather than reloads when today is on the page."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_script_anchors_restores_and_jumps():
    js = (ROOT / "static/js/grid.js").read_text()
    assert "sessionStorage" in js and '"grid-scroll:"' in js
    assert "dataset.start" in js
    assert '".grid-week.is-anchor"' in js
    assert "pagehide" in js and "htmx:beforeRequest" in js
    assert 'getElementById("grid-today")' in js and ".grid-day.is-today" in js
    assert "dataset.scroll" in js
    assert "preventDefault" in js and "scrollLeft" in js


def test_storage_access_is_guarded():
    """A private window or blocked site data throws on access; the grid
    must still load."""
    js = (ROOT / "static/js/grid.js").read_text()
    assert js.count("try {") >= 2
