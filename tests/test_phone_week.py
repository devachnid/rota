"""The week on a phone (review 7B): /rota/week/, a card per open day.

Read-only for everyone and no staffing warnings for anyone — it is for
looking someone up. Each day's lists come from the same place the day
view's do (rota/services/roster.py), and one test holds the two pages to
the same count.
"""

import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from rota.models import CoverageRule, PracticeSettings
from rota.services import grid as grid_svc
from tests.factories import (MON, make_absence, make_clinician, make_entry,
                             make_pattern, make_session_type)

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[1]
URL = f"/rota/week/?week={MON}"
TUE = MON + timedelta(days=1)


def _page(client, url=URL):
    PracticeSettings.load()
    resp = client.get(url)
    assert resp.status_code == 200
    return resp.content.decode()


def _card(html, day):
    start = html.index(f'id="d-{day}"')
    return html[html.rindex("<details", 0, start):html.index("</details>", start)]


def _summary(card):
    return card[card.index("<summary>"):card.index("</summary>")]


def test_it_needs_a_login(client):
    assert client.get("/rota/week/").status_code == 302


def test_a_card_per_open_day_in_order_with_a_strip_to_jump(gp_client):
    html = _page(gp_client)
    ids = re.findall(r'<details class="wk-day[^"]*" id="d-([\d-]+)"', html)
    assert ids == [str(MON + timedelta(days=i)) for i in range(5)]
    assert re.findall(r'<nav class="wk-strip".*?</nav>', html, re.S)[0].count("<a ") == 5


def test_today_is_open_and_the_rest_are_closed(gp_client, monkeypatch):
    monkeypatch.setattr(grid_svc, "_today", lambda: TUE)
    html = _page(gp_client)
    assert re.search(rf'<details class="wk-day is-today" id="d-{TUE}" open>', html)
    assert html.count("<details class=\"wk-day") == 5 and html.count(" open>") == 1
    assert 'aria-current="date"' in html


def test_another_week_opens_nothing(gp_client, monkeypatch):
    monkeypatch.setattr(grid_svc, "_today", lambda: MON - timedelta(days=30))
    assert " open>" not in _page(gp_client)


def test_a_closed_card_still_says_who_is_on_duty(gp_client):
    """The question a phone is opened for should not take a tap: the
    pinned roles are in the summary, which shows while the card is shut."""
    duty = make_session_type("Duty", code="DUTY", pin_on_day_view=True)
    a, b = make_clinician("Blake Rowe"), make_clinician("Indigo Ames")
    make_entry(a, day=TUE, part="AM", session_type=duty)
    make_entry(b, day=TUE, part="PM", session_type=duty)
    summary = _summary(_card(_page(gp_client), TUE))
    assert re.search(r'class="wk-pin-role"[^>]*>Duty</span>', summary)
    assert "Blake Rowe <span class=\"wk-part\">AM</span>" in summary
    assert "Indigo Ames <span class=\"wk-part\">PM</span>" in summary
    assert "in &middot;" in summary and "on leave" in summary


def test_it_is_read_only_even_for_an_admin(admin_client):
    c = make_clinician("Alice Adams")
    make_pattern(c)
    make_entry(c, day=TUE, part="AM")
    html = _page(admin_client)
    main = html[html.index('<main class="main">'):html.index("</main>")]
    assert "hx-get" not in main and "hx-post" not in main and 'tabindex="0"' not in main


def test_no_staffing_warnings_even_for_an_admin(admin_client):
    CoverageRule.objects.create(session_type=make_session_type("Duty", code="DUTY"))
    make_pattern(make_clinician("Alice Adams"))
    html = _page(admin_client)
    assert "No Duty cover" not in html and 'class="alert' not in html


def test_a_gp_sees_published_sessions_and_an_admin_the_drafts_too(gp_client, admin_client):
    c = make_clinician("Alice Adams")
    make_pattern(c)
    make_entry(c, day=TUE, part="AM", session_type=make_session_type("Routine", code="ROUT"))
    make_entry(c, day=TUE, part="PM", is_published=False,
               session_type=make_session_type("Urgent", code="URG"))
    gp = _card(_page(gp_client), TUE)
    assert "ROUT" in gp and "URG" not in gp
    admin = _card(_page(admin_client), TUE)
    assert "URG" in admin and "is-draft" in admin


def test_your_own_row_is_marked(gp_client, gp_user):
    me = make_clinician("Casey Stone", user=gp_user)
    make_pattern(me)
    make_entry(me, day=TUE, part="AM")
    card = _card(_page(gp_client), TUE)
    assert re.search(r'<div class="wk-row mine">\s*<span class="wk-who">Casey Stone', card)


def test_leave_and_absence_are_listed_after_the_roster(gp_client):
    make_pattern(make_clinician("Alice Adams"))
    away = make_clinician("Drew Tanner")
    make_pattern(away)
    make_absence(away, TUE)
    make_pattern(make_clinician("Emery Vale"), weekdays=(0, 2, 3, 4))  # Tuesdays off
    card = _card(_page(gp_client), TUE)
    assert re.search(r"<b>On leave</b> Drew Tanner( \(\w+\))?</p>", card)
    assert "<b>Not in</b> Emery Vale" in card


def test_a_closed_day_says_so(gp_client):
    from rota.models import ClosedDay
    ClosedDay.objects.create(day=TUE, reason="Bank holiday")
    summary = _summary(_card(_page(gp_client), TUE))
    assert "Bank holiday" in summary and ">closed<" in summary


def test_it_agrees_with_the_day_view(gp_client):
    """Both pages build their lists in rota/services/roster.py; this holds
    them to the same answer about the same day."""
    for name in ("Alice Adams", "Blake Rowe", "Casey Stone"):
        c = make_clinician(name)
        make_pattern(c)
        make_entry(c, day=TUE, part="AM")
    make_absence(make_clinician("Drew Tanner"), TUE)
    day = _page(gp_client, f"/rota/day/{TUE}/")
    in_day, leave_day = re.search(r"(\d+) in &middot; (\d+) on leave", day).groups()
    card = _summary(_card(_page(gp_client), TUE))
    assert f"{in_day} in &middot; {leave_day} on leave" in card


def test_the_week_steps_a_week_at_a_time(gp_client):
    html = _page(gp_client)
    assert f'href="?week={MON - timedelta(days=7)}"' in html
    assert f'href="?week={MON + timedelta(days=7)}"' in html
    assert f'<a href="/rota/?week={MON}">Open this week on the grid</a>' in html


def test_it_does_not_query_per_clinician(gp_client):
    def grow(n, start):
        rout = make_session_type("Routine", code="ROUT")
        for i in range(start, start + n):
            c = make_clinician(f"Clinician {i:02d}")
            make_pattern(c)
            for d in range(5):
                make_entry(c, day=MON + timedelta(days=d), part="AM", session_type=rout)
    grow(3, 0)
    _page(gp_client)
    with CaptureQueriesContext(connection) as before:
        _page(gp_client)
    grow(12, 3)
    with CaptureQueriesContext(connection) as after:
        _page(gp_client)
    assert len(after) == len(before)


def test_the_phones_week_tab_opens_it(gp_client):
    html = _page(gp_client)
    bar = html[html.index('<nav class="tabbar"'):]
    assert re.search(r'<a href="/rota/week/" class="tabbar-item is-active">Week</a>', bar)
    grid = _page(gp_client, f"/rota/?week={MON}")
    grid_bar = grid[grid.index('<nav class="tabbar"'):]
    assert re.search(r'<a href="/rota/week/" class="tabbar-item is-active">Week</a>', grid_bar)


def test_the_grid_offers_the_list_on_a_phone(gp_client):
    from tests.test_css_cascade import RULES
    grid = _page(gp_client, f"/rota/?week={MON}")
    assert f'<p class="phone-only wk-list-link"><a href="/rota/week/?week={MON}">' in grid
    shown = [r for r in RULES if r.selector == ".phone-only" and r.media == "(max-width: 640px)"]
    assert shown and shown[0].declarations["display"] == "block"


def test_the_day_strip_opens_the_card_it_jumps_to():
    js = (ROOT / "static" / "js" / "week.js").read_text()
    assert "card.open = true" in js and "location.hash" in js


def test_someone_pinned_but_on_leave_is_marked_and_their_leave_named(gp_client):
    """Seen in a browser: Breathe had Drew on holiday on a Tuesday he was
    also rostered on Duty. The pinned line said he was on Duty and the
    leave line said "Drew Tanner (Duty)"."""
    duty = make_session_type("Duty", code="DUTY", pin_on_day_view=True)
    drew = make_clinician("Drew Tanner")
    make_pattern(drew)
    make_entry(drew, day=TUE, part="AM", session_type=duty)
    make_absence(drew, TUE)
    card = _card(_page(gp_client), TUE)
    assert re.search(r'Drew Tanner <span class="wk-part">AM</span> <span class="wk-clash">— on leave</span>', _summary(card))
    assert "<b>On leave</b> Drew Tanner (Holiday)</p>" in card


def test_the_day_views_pinned_chip_is_ringed_for_a_clash_too(gp_client):
    duty = make_session_type("Duty", code="DUTY", pin_on_day_view=True)
    drew = make_clinician("Drew Tanner")
    make_pattern(drew)
    make_entry(drew, day=TUE, part="AM", session_type=duty)
    make_absence(drew, TUE)
    day = _page(gp_client, f"/rota/day/{TUE}/")
    pinned = day[day.index('class="day-pinned"'):day.index('<table class="day-roster">')]
    assert "chip is-clash" in pinned
