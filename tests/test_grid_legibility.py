"""Two ways a session type can be configured so the week grid cannot show
it: a code longer than the cell can print, and a colour another type has
already taken. Both are invisible in the admin — the type looks fine on its
own page — so the dashboard counts them and links to the list.
"""

import pytest

from rota.services.legibility import CODE_FITS, grid_legibility
from tests.factories import make_session_type

pytestmark = pytest.mark.django_db


def test_a_code_that_fits_is_not_reported():
    make_session_type("Duty", code="DUTY", colour="red-strong")
    assert grid_legibility().clipped == []


def test_a_code_too_long_for_the_cell_is_reported_by_name():
    make_session_type("PMC Routine", code="PMC Rout", colour="pink-strong")
    make_session_type("Minor Surgery", code="Minor Op", colour="blue-strong")
    make_session_type("Duty", code="DUTY", colour="red-strong")
    assert grid_legibility().clipped == ["Minor Surgery", "PMC Routine"]


def test_the_limit_is_what_the_cell_actually_prints():
    """Six characters, measured against the 3.5rem column — the number is
    the point, so it is asserted rather than left to drift."""
    assert CODE_FITS == 6
    make_session_type("Six", code="ABCDEF", colour="red-soft")
    make_session_type("Seven", code="ABCDEFG", colour="blue-soft")
    assert grid_legibility().clipped == ["Seven"]


def test_two_types_on_one_colour_are_reported_together():
    make_session_type("USW", code="USW", colour="magenta-strong")
    make_session_type("Vasectomy", code="Vas", colour="magenta-strong")
    make_session_type("Duty", code="DUTY", colour="red-strong")
    assert grid_legibility().sharing == [("magenta-strong", ["USW", "Vasectomy"])]


def test_a_soft_and_a_strong_of_one_hue_are_two_colours():
    """The palette's whole point: a related pair may share a hue at two
    weights, and that is not a collision."""
    make_session_type("SDL", code="SDL", colour="violet-strong")
    make_session_type("VTS", code="VTS", colour="violet-soft")
    assert grid_legibility().sharing == []


def test_leave_is_allowed_to_share_the_neutral():
    """Migration 0022 seeds Annual leave and Other leave on one neutral, and
    that is the palette working as designed: leave is grey so it does not
    compete with the clinical sessions around it. A count that flagged it
    would be a count nobody could ever clear."""
    make_session_type("Annual leave", code="AL", colour="neutral-strong")
    make_session_type("Other leave", code="OFF", colour="neutral-strong")
    make_session_type("Sick", code="SICK", colour="neutral-soft")
    assert grid_legibility().sharing == []


def test_the_dashboard_counts_types_not_collisions(admin_client):
    """Three types on one colour is three types to fix, and the link has to
    open the list they are in."""
    from rota.admin_dashboard import health
    for name in ("USW", "Vasectomy", "LARCs"):
        make_session_type(name, code=name[:4], colour="magenta-strong")
    # Not amber: migration 0022 seeds Sick there, and a fixture that lands
    # on a seeded tint would be counting its own collision.
    make_session_type("PMC Routine", code="PMC Rout", colour="blue-strong")
    lines = {h["label"]: h for h in health()}
    assert lines["Session types sharing a colour"]["count"] == 3
    assert lines["Session codes too long for the grid"]["count"] == 1
    for label in ("Session types sharing a colour", "Session codes too long for the grid"):
        assert admin_client.get(lines[label]["url"]).status_code == 200


def test_a_tidy_practice_gets_zeroes(admin_client):
    from rota.admin_dashboard import health
    make_session_type("Duty", code="DUTY", colour="red-strong")
    make_session_type("Routine", code="ROUT", colour="azure-soft")
    lines = {h["label"]: h for h in health()}
    assert lines["Session types sharing a colour"]["count"] == 0
    assert lines["Session codes too long for the grid"]["count"] == 0
