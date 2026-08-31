"""Query counts and rendered-page hygiene for the two new screens.

The counts are asserted as "does not grow", not as an exact number: an exact
count is a tripwire that fires on every unrelated change, and what matters is
that adding a clinician does not add a query.

`django_assert_num_queries(None)` (as sketched in the task brief) is not a
valid pytest-django API — the fixture expects an integer, and passing None
does not give a capture-only context. `CaptureQueriesContext` is what the
rest of this codebase already uses for this shape of test (see
tests/test_grid_rendering.py::test_the_grid_query_count_does_not_grow_with_clinicians_or_leave),
so it is used here too: capture a warm baseline, add more data, capture
again, and assert the count did not grow.
"""

from datetime import date, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from rota.models import DayNote, PracticeSettings
from tests.factories import (make_clinician, make_entry, make_pattern,
                             make_session_type)

pytestmark = pytest.mark.django_db

TUE = date(2026, 9, 8)

LEAKED = ["{#", "#}", "{%", "TODO:", "FIXME:", "XXX:", "vestigial"]


def _populate(n, day=TUE):
    rout = make_session_type("Routine", code="ROUT")
    for i in range(n):
        c = make_clinician(f"Clinician {i:02d}")
        make_pattern(c)
        make_entry(c, day=day, part="AM", session_type=rout)
        make_entry(c, day=day, part="PM", session_type=rout)


def test_the_day_view_does_not_query_per_clinician(gp_client, gp_user):
    PracticeSettings.load()
    make_clinician("Viewer", user=gp_user)
    _populate(3)
    url = f"/rota/day/{TUE.isoformat()}/"
    gp_client.get(url)  # warm caches: session lookups, content negotiation

    with CaptureQueriesContext(connection) as ctx:
        resp = gp_client.get(url)
    assert resp.status_code == 200
    assert "ROUT" in resp.content.decode(), (
        "the roster must actually be rendering sessions at baseline, or "
        "this measures an empty page"
    )
    baseline = len(ctx)

    _populate(12, day=TUE)
    with CaptureQueriesContext(connection) as ctx:
        resp = gp_client.get(url)
    assert resp.status_code == 200
    assert "ROUT" in resp.content.decode(), (
        "the roster must still be rendering sessions after growing it, or "
        "this measures an empty page"
    )
    assert len(ctx) == baseline, (
        "the day view issues more queries with more clinicians on the "
        "roster — something is asking per row"
    )


def test_my_schedule_does_not_query_per_week(gp_client, gp_user):
    PracticeSettings.load()
    c = make_clinician(user=gp_user)
    make_pattern(c)
    gp_client.get("/me/")  # warm caches

    with CaptureQueriesContext(connection) as ctx:
        resp = gp_client.get("/me/")
    assert resp.status_code == 200
    baseline = len(ctx)

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    rout = make_session_type("Routine", code="ROUT")
    for n in range(20):
        day = monday + timedelta(days=n)
        if day.weekday() < 5:
            make_entry(c, day=day, part="AM", session_type=rout)

    with CaptureQueriesContext(connection) as ctx:
        resp = gp_client.get("/me/")
    assert resp.status_code == 200
    assert "ROUT" in resp.content.decode(), (
        "the populated entries must actually be rendering as sessions, or "
        "this measures an empty page"
    )
    assert len(ctx) == baseline, (
        "My Schedule issues more queries with more weeks of entries — "
        "something is asking per row"
    )


@pytest.mark.parametrize("url", ["/rota/day/", "/me/"])
def test_no_developer_notes_reach_the_page(admin_client, url):
    PracticeSettings.load()
    DayNote.objects.create(day=date.today(), text="A normal note")
    html = admin_client.get(url).content.decode()
    for frag in LEAKED:
        assert frag not in html, f"{url} renders {frag!r} to the page"
