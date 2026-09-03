"""My Schedule's agenda: four weeks as blocks, open days only.

Two rules from the spec that pull in opposite directions and are easy to
conflate:
  - a day the SURGERY is closed is not shown at all
  - a day you do not work, on an open day, IS shown, as dashes
The first is not your day off. The second is.

Fix round 1 added a third: a day is shown if the surgery is open on it OR
the clinician has an entry on it. A closed day (or a weekday outside
open_weekdays, like a weekend) with nothing on it stays hidden — that's the
rule above. But hiding a REAL published session from the person rostered to
it is worse than the tidiness of omitting an empty row, so a closed day (or
non-open weekday) that does carry an entry is shown anyway.
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


# -------------------------------------------------- reduced emphasis ---

def test_a_full_day_of_leave_is_flagged_and_rendered_at_reduced_emphasis(
        gp_client, gp_user):
    """Spec: "Leave days render at reduced emphasis." There was no absence
    branch in my_schedule.html and no modifier in screens.css at all —
    every day rendered identically regardless of category."""
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    make_entry(c, day=monday, part="AM", session_type=al)
    make_entry(c, day=monday, part="PM", session_type=al)
    days = _ctx(gp_client)["weeks"][0]["days"]
    row = next(d for d in days if d["day"] == monday)
    assert row["is_leave"] is True
    assert 'class="ms-day is-leave"' in _html(gp_client)


def test_a_working_day_is_not_flagged_as_leave(gp_client, gp_user):
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    make_entry(c, day=monday, part="AM",
               session_type=make_session_type("Routine", code="ROUT"))
    days = _ctx(gp_client)["weeks"][0]["days"]
    row = next(d for d in days if d["day"] == monday)
    assert row["is_leave"] is False


def test_a_half_day_of_leave_is_not_flagged_as_a_leave_day(gp_client, gp_user):
    """Reduced emphasis is for a day that IS leave, not a day that merely
    contains some — a half-and-half mix must keep the working half at full
    weight, so the row as a whole stays unflagged."""
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    rout = make_session_type("Routine", code="ROUT")
    make_entry(c, day=monday, part="AM", session_type=al)
    make_entry(c, day=monday, part="PM", session_type=rout)
    days = _ctx(gp_client)["weeks"][0]["days"]
    row = next(d for d in days if d["day"] == monday)
    assert row["is_leave"] is False


def test_a_dashes_only_day_is_not_flagged_as_leave(gp_client, gp_user):
    """A day you simply do not work is not the same state as a day you are
    on leave from — dashes must not pick up the same reduced-emphasis
    treatment leave gets."""
    c = make_clinician(user=gp_user)
    make_pattern(c, weekdays=(5, 6))  # weekend only; Monday is a dash day
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    days = _ctx(gp_client)["weeks"][0]["days"]
    row = next((d for d in days if d["day"] == monday), None)
    if row is not None:  # Monday is a non-open weekday and may be hidden
        assert row["is_leave"] is False


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


def test_the_agenda_comes_before_your_requests(gp_client, gp_user):
    """The old order made a GP scroll past secondary content to find out
    where they are working tomorrow. The balance is gone; the property is
    not."""
    from rota.models import SwapRequest
    from tests.factories import MON
    c = make_clinician(user=gp_user)
    other = make_clinician("Other Person")
    SwapRequest.objects.create(proposer=c, proposer_day=MON, proposer_part="AM",
                                colleague=other, colleague_day=MON, colleague_part="PM")
    html = _html(gp_client)
    assert html.index("ms-weeks") < html.index("ms-requests")


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


# --------------------------------------------------------- fix round 1 ---

def test_a_closed_day_with_an_entry_is_shown(gp_client, gp_user):
    """The other half of the rule fix round 1 added: hiding a real
    published session from the person rostered to it is worse than the
    tidiness of hiding an empty closed day."""
    c = make_clinician(user=gp_user)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    victim = monday if monday != today else monday + timedelta(days=1)
    ClosedDay.objects.create(day=victim, reason="Bank holiday")
    make_entry(c, day=victim, part="AM",
               session_type=make_session_type("Routine", code="ROUT"))
    days = [d["day"] for d in _ctx(gp_client)["weeks"][0]["days"]]
    assert victim in days


def test_a_closed_day_with_no_entry_still_stays_absent(gp_client, gp_user):
    """Same closed day, no entry this time: still not your day off, still
    not shown. Sits next to the entry case above so the two halves of the
    rule are pinned side by side, rather than trusting that
    test_a_closed_day_is_absent_from_its_block alone still covers this once
    the day-inclusion condition changed."""
    make_clinician(user=gp_user)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    victim = monday if monday != today else monday + timedelta(days=1)
    ClosedDay.objects.create(day=victim, reason="Bank holiday")
    days = [d["day"] for d in _ctx(gp_client)["weeks"][0]["days"]]
    assert victim not in days


def test_a_published_entry_on_a_non_open_weekday_is_not_swallowed(
        gp_client, gp_user, monkeypatch):
    """The bug this fix round exists for: test_my_schedule.py's
    test_shows_upcoming_sessions_and_balance creates an entry at
    today + 1 day with no weekday guard, so whenever the suite runs on a
    Friday or Saturday that entry lands on a weekend and used to vanish —
    roughly two days in seven. Pin a specific Friday rather than depend on
    when this test happens to run."""
    import rota.views.my_schedule as my_schedule_view

    friday = date(2026, 9, 4)
    assert friday.weekday() == 4  # confirms the fixture date is a Friday

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return friday

    monkeypatch.setattr(my_schedule_view, "date", _FixedDate)

    c = make_clinician(user=gp_user)
    saturday = friday + timedelta(days=1)
    assert saturday.weekday() == 5  # not in the default open_weekdays
    make_entry(c, day=saturday, part="AM",
               session_type=make_session_type("Routine", code="ROUT"))
    html = _html(gp_client)
    assert "ROUT" in html


def test_a_blank_open_weekdays_does_not_crash_the_page(gp_client, gp_user):
    """This branch was bitten by exactly this last phase — a blank
    open_weekdays made the grid raise IndexError on days[-1]. My Schedule's
    own day-building logic never indexes into an empty list, but nothing
    proved that until now."""
    make_clinician(user=gp_user)
    settings = PracticeSettings.load()
    settings.open_weekdays = ""
    settings.save()
    resp = gp_client.get("/me/")
    assert resp.status_code == 200
    assert all(w["days"] == [] for w in resp.context["weeks"])


def test_a_week_with_no_open_days_does_not_contradict_its_own_body(
        gp_client, gp_user):
    """A block with no days must not also claim "0 sessions" beside
    "Surgery closed all week" — that reads like an ordinary quiet week
    rather than a week the surgery was shut for."""
    make_clinician(user=gp_user)
    settings = PracticeSettings.load()
    settings.open_weekdays = ""
    settings.save()
    ctx = _ctx(gp_client)
    assert all(w["count_label"] == "" for w in ctx["weeks"])
    assert "ms-week-count" not in _html(gp_client)


# --------------------------------------------------------- fix round 2 ---

def test_today_is_working_even_when_the_surgery_is_closed(gp_client, gp_user):
    """The same rule _blocks() carries, applied to the Today box: a session
    the clinician actually has beats the closure. A closed "today" with an
    entry on it must report "working" and render that session, not the
    closure note — the Today-box instance of the same defect fix round 1
    closed for the week blocks. today_state's other two states — a closed
    day with no entry, and an open day with none — are pinned by
    test_today_says_closed_when_the_surgery_is_shut and
    test_today_says_not_in_when_you_have_no_sessions above, and both keep
    passing under the reordered condition."""
    c = make_clinician(user=gp_user)
    today = date.today()
    ClosedDay.objects.create(day=today, reason="Bank holiday")
    make_entry(c, day=today, part="AM",
               session_type=make_session_type("Routine", code="ROUT"))
    assert _ctx(gp_client)["today_state"] == "working"
    html = _html(gp_client)
    assert "ROUT" in html
    assert "Surgery closed" not in html


# ------------------------------------------------------ Breathe overlay ---

def test_a_gps_own_breathe_leave_shows_on_their_schedule(gp_client, gp_user):
    """The old agenda bypassed cell_state and so could never show leave. With
    Breathe as the source that would hide a GP's own leave from them."""
    from tests.factories import make_absence
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    tuesday = monday + timedelta(days=1)
    make_absence(c, tuesday)
    html = gp_client.get("/me/").content.decode()
    assert 'title="Holiday — from Breathe"' in html
    assert "AL" in html


def test_a_week_of_breathe_leave_reads_on_leave_all_week(gp_client, gp_user):
    from tests.factories import make_absence
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    make_absence(c, monday, monday + timedelta(days=4))
    PracticeSettings.load()
    weeks = gp_client.get("/me/").context["weeks"]
    assert weeks[0]["count_label"] == "On leave all week"


def test_today_reads_working_when_only_half_the_day_is_leave(gp_client, gp_user):
    from tests.factories import make_absence
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    if today.weekday() > 4:
        pytest.skip("weekend")
    make_absence(c, today, half_start=True, half_start_am_pm="AM")
    ctx = gp_client.get("/me/").context
    assert ctx["today_state"] == "working"
    assert ctx["today_cells"][0]["absence"] is not None
    assert ctx["today_cells"][1]["absence"] is None


def test_the_leave_balance_and_leave_requests_are_gone(gp_client, gp_user):
    make_clinician(user=gp_user)
    html = gp_client.get("/me/").content.decode()
    assert "ms-balance" not in html
    assert "Request leave" not in html
    assert "Propose a swap" in html, "swaps stay"


def test_a_closed_day_with_a_session_is_never_styled_as_leave(gp_client, gp_user):
    """A bank holiday inside a leave span, with a published session left on
    it: the row shows (a real session beats the closure) but must not take
    the leave style — that decision belongs to open days, the same guard
    today_state already applies. Before this, `on_leave` under an entry
    made the row read as a day off."""
    from tests.factories import make_absence
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    victim = monday if monday != today else monday + timedelta(days=1)
    ClosedDay.objects.create(day=victim, reason="Bank holiday")
    make_entry(c, day=victim, part="AM",
               session_type=make_session_type("Routine", code="ROUT"))
    make_absence(c, monday, monday + timedelta(days=4))
    rows = {d["day"]: d for d in _ctx(gp_client)["weeks"][0]["days"]}
    assert victim in rows, "a closed day with a session is still shown"
    assert rows[victim]["is_leave"] is False


def test_a_note_is_printed_in_the_week_row_and_the_today_box(gp_client, gp_user):
    c = make_clinician(user=gp_user)
    make_pattern(c)
    make_entry(c, day=date.today(), part="AM", note="Bring the laptop",
               session_type=make_session_type("Routine", code="ROUT"))
    PracticeSettings.load()
    html = gp_client.get("/me/").content.decode()
    assert html.count("has-note") == 2, "the today box and the week row"
    assert html.count('class="ms-note">AM — Bring the laptop<') == 2
