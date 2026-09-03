"""The day view's styling, checked for the two failures this project repeats.

Colour literals (every colour must come from tokens.css) and rules that are
written but never apply. Nothing here proves a browser paints the result.
"""

import re
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / "static" / "css" / "screens.css").read_text()


def test_the_day_view_section_exists():
    start = CSS.index("day view")
    end = CSS.index("reports", start)
    section = CSS[start:end]
    # Section must contain CSS rules (marked by opening braces), not just the marker
    assert '{' in section, "day view section contains no CSS rules"


def test_every_class_the_template_uses_is_styled():
    for cls in (".day-head", ".day-count", ".day-step", ".day-closed",
                ".day-pinned", ".day-roster", ".day-dash", ".day-not-in",
                ".day-note-text"):
        assert cls in CSS, f"{cls} appears in day.html but nowhere in screens.css"


def test_no_colour_literals_in_the_day_view_rules():
    start = CSS.index("day view")
    end = CSS.index("reports", start)
    section = CSS[start:end]
    # Ensure the section has actual content beyond the marker
    assert len(section.strip()) > len("day view"), "section appears empty"
    literals = re.findall(r"#[0-9A-Fa-f]{3,8}\b|\brgba?\(|\bhsla?\(", section)
    assert not literals, f"day view CSS hard-codes colours: {literals}"
