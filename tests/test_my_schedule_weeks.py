"""My Schedule's agenda: four weeks as blocks, open days only.

Two rules from the spec that pull in opposite directions and are easy to
conflate:
  - a day the SURGERY is closed is not shown at all
  - a day you do not work, on an open day, IS shown, as dashes
The first is not your day off. The second is.
"""

from datetime import date, timedelta

import pytest

from rota.models import ClosedDay, PracticeSettings
from tests.factories import (make_clinician, make_entry, make_pattern,
                             make_session_type)

pytestmark = pytest.mark.django_db


def _ctx(client):
    PracticeSettings.load()
    return client.get("/me/").context


def test_there_are_four_week_blocks(gp_client, gp_user):
    make_clinician(user=gp_user)
    assert len(_ctx(gp_client)["weeks"]) == 4


def test_the_first_block_is_headed_this_week(gp_client, gp_user):
    make_clinician(user=gp_user)
    assert _ctx(gp_client)["weeks"][0]["heading"] == "This week"


def test_later_blocks_are_headed_with_their_monday(gp_client, gp_user):
    make_clinician(user=gp_user)
    weeks = _ctx(gp_client)["weeks"]
    assert weeks[1]["heading"].startswith("Week of ")


def test_a_closed_day_is_absent_from_its_block(gp_client, gp_user):
    make_clinician(user=gp_user)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    # pick an open weekday in this week that is not today
    victim = monday if monday != today else monday + timedelta(days=1)
    ClosedDay.objects.create(day=victim, reason="Bank holiday")
    days = [d["day"] for d in _ctx(gp_client)["weeks"][0]["days"]]
    assert victim not in days


def test_an_open_day_you_do_not_work_is_present_as_dashes(gp_client, gp_user):
    c = make_clinician(user=gp_user)
    make_pattern(c, weekdays=(0,))  # Mondays only
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    tuesday = monday + timedelta(days=1)
    row = next(d for d in _ctx(gp_client)["weeks"][0]["days"]
               if d["day"] == tuesday)
    assert row["am"] is None and row["pm"] is None


def test_the_count_label_counts_sessions(gp_client, gp_user):
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    rout = make_session_type("Routine", code="ROUT")
    make_entry(c, day=monday, part="AM", session_type=rout)
    make_entry(c, day=monday, part="PM", session_type=rout)
    assert _ctx(gp_client)["weeks"][0]["count_label"] == "2 sessions"


def test_one_session_is_singular(gp_client, gp_user):
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    make_entry(c, day=monday, part="AM",
               session_type=make_session_type("Routine", code="ROUT"))
    assert _ctx(gp_client)["weeks"][0]["count_label"] == "1 session"


def test_a_week_of_nothing_but_absence_says_so(gp_client, gp_user):
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    for n in range(5):
        for part in ("AM", "PM"):
            make_entry(c, day=monday + timedelta(days=n), part=part,
                       session_type=al)
    assert _ctx(gp_client)["weeks"][0]["count_label"] == "On leave all week"


def test_today_says_not_in_when_you_have_no_sessions(gp_client, gp_user):
    c = make_clinician(user=gp_user)
    make_pattern(c, weekdays=())
    assert _ctx(gp_client)["today_state"] == "not_in"


def test_today_says_closed_when_the_surgery_is_shut(gp_client, gp_user):
    make_clinician(user=gp_user)
    ClosedDay.objects.create(day=date.today(), reason="Bank holiday")
    assert _ctx(gp_client)["today_state"] == "closed"


def test_today_is_working_when_you_have_a_session(gp_client, gp_user):
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    if today.weekday() > 4:
        pytest.skip("weekend: the practice is closed and this case cannot arise")
    make_entry(c, day=today, part="AM",
               session_type=make_session_type("Routine", code="ROUT"))
    assert _ctx(gp_client)["today_state"] == "working"


# ------------------------------------------------------------- rendering ---

def _html(client):
    PracticeSettings.load()
    return client.get("/me/").content.decode()


def test_the_five_column_table_is_gone(gp_client, gp_user):
    """The old agenda was a table in a sideways scroller, which is the thing
    this phase exists to remove from this screen."""
    make_clinician(user=gp_user)
    assert "table-scroll" not in _html(gp_client)


def test_the_agenda_comes_before_the_leave_balance(gp_client, gp_user):
    """The old order made a GP scroll past their leave balance to find out
    where they are working tomorrow."""
    make_clinician(user=gp_user)
    html = _html(gp_client)
    assert html.index("ms-weeks") < html.index("ms-balance")


def test_a_swap_awaiting_you_comes_before_everything(gp_client, gp_user):
    from rota.models import SwapRequest
    from tests.factories import MON
    me = make_clinician("Me Person", user=gp_user)
    other = make_clinician("Other Person")
    SwapRequest.objects.create(
        proposer=other, proposer_day=MON, proposer_part="AM",
        colleague=me, colleague_day=MON, colleague_part="PM")
    html = _html(gp_client)
    assert html.index("ms-awaiting") < html.index("ms-today")


def test_not_in_today_is_worded_for_a_human(gp_client, gp_user):
    c = make_clinician(user=gp_user)
    make_pattern(c, weekdays=())
    if date.today().weekday() > 4:
        pytest.skip("weekend: today_state is 'closed', not 'not_in'")
    assert "Not in today" in _html(gp_client)
