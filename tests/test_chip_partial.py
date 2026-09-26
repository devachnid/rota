"""One chip template. The session chip and the Breathe absence chip were
written out five times across the grid, the day view and My Schedule, and
the copies had drifted — the clash tooltip on some and not others, the site
marker missing from the day view's on-leave table. They are one include
now, with the two per-screen differences as explicit opt-ins."""

from pathlib import Path

import pytest

from rota.models import PracticeSettings
from tests.factories import (MON, make_absence, make_clinician, make_entry,
                             make_pattern, make_session_type)

pytestmark = pytest.mark.django_db
TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


def test_only_the_partial_draws_a_chip():
    """A tripwire: the tint and the code are what a chip is made of, so a
    template printing either outside _chip.html is a sixth copy starting."""
    drawing = sorted(str(p.relative_to(TEMPLATES)) for p in TEMPLATES.rglob("*.html")
                     if "tint.key" in p.read_text() or "session_type.code" in p.read_text())
    assert drawing == ["rota/_chip.html"]


def test_every_chip_screen_uses_it():
    for name in ("_grid_row.html", "day.html", "my_schedule.html"):
        assert '{% include "rota/_chip.html"' in (TEMPLATES / "rota" / name).read_text(), name


def _clash_setup():
    PracticeSettings.load()
    c = make_clinician("Alice Adams")
    make_pattern(c)
    make_entry(c, part="AM", session_type=make_session_type("Routine", code="ROUT"))
    make_absence(c, MON)
    return c


def test_the_day_view_puts_the_clash_on_the_chip(gp_client):
    _clash_setup()
    html = gp_client.get(f"/rota/day/{MON}/").content.decode()
    assert 'class="chip is-clash" title="On Breathe leave: Holiday"' in html


def test_the_grid_keeps_the_clash_in_the_cell_tooltip_not_the_chip(admin_client):
    """A title on the chip would hide the cell's own, which carries the
    session's name and site as well as the clash."""
    _clash_setup()
    html = admin_client.get(f"/rota/?week={MON}").content.decode()
    assert 'class="chip is-clash"' in html
    assert 'class="chip is-clash" title=' not in html
    assert "— On Breathe leave: Holiday" in html


def test_the_strike_is_the_grids_and_the_admins(admin_client, gp_client, admin_user):
    from rota.models import RotaEntry
    from rota.services import entries as entries_svc
    c = _clash_setup()
    entries_svc.set_entered(admin_user, RotaEntry.objects.get(clinician=c), True)
    assert "is-entered" in admin_client.get(f"/rota/?week={MON}").content.decode()
    assert "is-entered" not in gp_client.get(f"/rota/?week={MON}").content.decode()
    assert "is-entered" not in admin_client.get(f"/rota/day/{MON}/").content.decode()
