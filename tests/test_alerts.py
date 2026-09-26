"""A line that says something is wrong now looks like it. Staffing gaps,
ceilings, a form asking to be saved again and a swap that cannot be
approved were all .warn — 11.5px of red text with no ground, lighter than
the day note beside them. They are .alert now: the soft ground and a rule
in the level's colour, the vocabulary the badges and messages already use.
The level comes from the warning itself, and the two a day header has room
for are the serious ones.
"""

import re
from pathlib import Path

import pytest

from rota.models import PracticeSettings
from rota.services.warnings import Warning
from tests.factories import MON, make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db
CSS = (Path(__file__).resolve().parents[1] / "static" / "css" / "components.css").read_text()


def _rule(selector):
    body = CSS[CSS.index(selector + " {"):]
    return body[:body.index("}")]


@pytest.mark.parametrize("code", ["coverage", "staffing", "group", "breathe"])
def test_an_uncovered_session_or_an_absent_person_is_danger(code):
    assert Warning(code, "AM", "…").level == "danger"


def test_a_ceiling_is_a_warning():
    """A soft limit someone chose — over it is worth a look, not an alarm."""
    assert Warning("ceiling", None, "…").level == "warning"


def _day_header(html, day):
    start = html.index(f'hx-get="/rota/daynote/{day}/"')
    return html[html.rindex("<th", 0, start):html.index("</th>", start)]


def test_the_header_keeps_its_two_lines_for_the_serious_ones(admin_client):
    """day_warnings lists a ceiling before the staffing check, so without
    ordering the header showed "Too many Urgent" and folded an uncovered
    afternoon into "+1 more"."""
    PracticeSettings.objects.update_or_create(pk=1, defaults={"min_clinical_per_session": 3})
    urgent = make_session_type("Urgent", code="URG", max_per_session=1)
    a, b = make_clinician("Alice Adams"), make_clinician("Beth Brown")
    make_entry(a, part="AM", session_type=urgent)
    make_entry(b, part="AM", session_type=urgent)
    make_entry(b, part="PM", session_type=urgent)
    header = _day_header(admin_client.get(f"/rota/?week={MON}").content.decode(), MON)
    shown = re.findall(r'<div class="alert alert-compact alert-(\w+)">([^<]*)</div>', header)
    assert [level for level, _ in shown] == ["danger", "danger"]
    assert not any("Too many" in text for _, text in shown)
    assert "+1 more" in header
    assert "Too many Urgent (AM)" in header  # still in the header's tooltip


def test_a_ceiling_in_the_week_header_is_amber(admin_client):
    PracticeSettings.load()
    urgent = make_session_type("Urgent", code="URG", max_per_week=1)
    a = make_clinician("Alice Adams")
    make_entry(a, part="AM", session_type=urgent)
    make_entry(a, part="PM", session_type=urgent)
    html = admin_client.get(f"/rota/?week={MON}").content.decode()
    assert 'class="alert alert-compact alert-warning">Too many Urgent this week' in html


def test_the_breathe_banner_is_a_warning_not_a_gap(admin_client):
    PracticeSettings.load()
    make_clinician("Alice Adams")
    html = admin_client.get(f"/rota/?week={MON}").content.decode()
    assert '<div class="alert alert-warning">1 clinician not linked to Breathe' in html


def test_the_cell_forms_prompt_to_save_again_is_announced_as_a_warning(admin_client):
    """"Not usually eligible — save again" is a question, not a refusal."""
    PracticeSettings.load()
    c = make_clinician("Alice Adams")
    st = make_session_type("Minor Surgery", code="MIN")
    st.allowed_clinicians.add(make_clinician("Beth Brown"))
    resp = admin_client.post("/rota/assign/", {
        "clinician_id": c.id, "day": MON.isoformat(), "part": "AM",
        "session_type_id": st.id, "note": ""})
    assert '<div class="alert alert-warning" role="alert">' in resp.content.decode()


def test_the_css_is_one_rule_set_and_two_tones():
    """The level swaps two custom properties; the ground, the rule and the
    compact text colour all read them, so a new level is two lines."""
    alert = _rule(".alert")
    assert "background: var(--tone-soft)" in alert
    assert "border-left: 4px solid var(--tone)" in alert
    assert "--tone: var(--danger)" in alert, "unlabelled is danger, never silent"
    warning = _rule(".alert-warning")
    assert "--tone: var(--warning)" in warning and "--tone-soft: var(--warning-soft)" in warning
    assert "color: var(--tone)" in _rule(".alert-compact")


def test_inline_warn_is_left_for_inline_text():
    """A phrase inside a table cell or a sentence keeps the plain red text;
    a ground and a rule on an inline span would break mid-line."""
    warn = _rule(".warn")
    assert "background" not in warn and "border" not in warn
