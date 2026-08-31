"""What a grid cell shows, and why.

Cell precedence:
    entry exists                -> the entry
    on_leave and ghostable      -> a ghosted leave chip
    works_on                    -> grey: working, nothing allocated
    otherwise                   -> blank: not working

The colours are the reverse of what shipped: blank now means "not here", grey
means "here and unallocated" — the state that needs attention.
"""

import re
from datetime import date, timedelta

import pytest

from rota.models import (ClosedDay, LeaveRequest, PatternSlot,
                         PracticeSettings)
from tests.factories import make_clinician, make_entry, make_session_type

MON = date(2026, 9, 7)


def _pattern(c, weekday, part, works=True):
    PatternSlot.objects.create(clinician=c, weekday=weekday, part=part,
                               works=works, effective_from=date(2025, 1, 1))


def _full_pattern(c, weekdays=range(5)):
    for weekday in weekdays:
        for part in ("AM", "PM"):
            _pattern(c, weekday, part)


def _cells(client, day=MON):
    PracticeSettings.load()
    return client.get(f"/rota/?week={day.isoformat()}").content.decode()


# The admin grid puts a per-cell hx-get on every <td>, which is the only thing
# in the markup that says which clinician, day and part a chip belongs to.
_CELL_RE = re.compile(
    r"/rota/cell/(?P<cid>\d+)/(?P<day>\d{4}-\d\d-\d\d)/(?P<part>AM|PM)/"
    r'.*?<span class="chip(?P<classes>[^"]*)"',
    re.S,
)


def _chips(html):
    """{(clinician_id, ISO day, part): the chip's modifier classes}.

    Counting classes across the whole page cannot tell `empty-slot` on the
    worked cell from `is-off` on it: swap the two template branches and every
    total is identical. This reads which class landed on which cell.
    """
    return {
        (int(m["cid"]), m["day"], m["part"]): m["classes"].strip()
        for m in _CELL_RE.finditer(html)
    }


def _iso(offset):
    return (MON + timedelta(days=offset)).isoformat()


@pytest.mark.django_db
def test_a_worked_but_unallocated_session_is_grey(admin_client):
    """Per cell, not per page. `"empty-slot" in html` was true of the exact
    inversion this task shipped to fix: one clinician working Monday AM gives
    the page 1 empty-slot and 9 is-off, and swapping the template's two
    branches gives it 9 and 1 — that assertion passes either way."""
    c = make_clinician("Grey", initials="GY")
    _pattern(c, 0, "AM")
    chips = _chips(_cells(admin_client))
    assert chips[(c.id, _iso(0), "AM")] == "empty-slot", (
        "the worked, unallocated session should carry the grey class"
    )
    assert chips[(c.id, _iso(0), "PM")] == "is-off"
    assert chips[(c.id, _iso(1), "AM")] == "is-off"
    assert sum(1 for v in chips.values() if v == "empty-slot") == 1, (
        "only the one worked session should be grey"
    )


@pytest.mark.django_db
def test_a_non_working_session_is_blank(admin_client):
    """`"unavail" not in html` was true of any implementation whatsoever —
    the class was deleted. Assert the class that is actually expected."""
    c = make_clinician("Blank", initials="BL")
    _pattern(c, 0, "AM", works=False)
    chips = _chips(_cells(admin_client))
    assert chips[(c.id, _iso(0), "AM")] == "is-off", (
        "a session the pattern says is not worked should render blank"
    )
    assert set(chips.values()) == {"is-off"}, (
        "this clinician works nothing, so nothing should be grey"
    )
    assert "unavail" not in _cells(admin_client), "the old class is gone"


@pytest.mark.django_db
def test_approved_leave_ghosts_on_a_session_the_clinician_works(admin_client):
    """Approval should have written an entry here and did not — the ghost is
    the signal that something went wrong."""
    c = make_clinician("Ghosted", initials="GH")
    _pattern(c, 0, "AM")
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    LeaveRequest.objects.create(clinician=c, session_type=al,
                                start_date=MON, end_date=MON,
                                status=LeaveRequest.Status.APPROVED)
    html = _cells(admin_client)
    assert "is-ghost" in html
    assert "AL" in html


@pytest.mark.django_db
def test_a_part_timer_gets_no_ghost_on_their_non_working_days(admin_client):
    """The noise case. Ghosting every session a leave request spans would put
    chips on every part-timer's days off, every time they took leave."""
    c = make_clinician("Parttime", initials="PT")
    _pattern(c, 0, "AM")            # works Monday AM only
    _pattern(c, 0, "PM", works=False)
    al = make_session_type("Annual Leave", code="AL2", category="ABSENCE")
    LeaveRequest.objects.create(clinician=c, session_type=al,
                                start_date=MON, end_date=MON + timedelta(days=4),
                                status=LeaveRequest.Status.APPROVED)
    html = _cells(admin_client)
    assert html.count("is-ghost") == 1, (
        f"expected one ghost (Monday AM), got {html.count('is-ghost')}"
    )


@pytest.mark.django_db
def test_a_clinician_with_no_pattern_at_all_gets_ghosts(admin_client):
    """The original complaint: leave approved, nothing anywhere."""
    c = make_clinician("Nopattern", initials="NP")
    al = make_session_type("Annual Leave", code="AL3", category="ABSENCE")
    LeaveRequest.objects.create(clinician=c, session_type=al,
                                start_date=MON, end_date=MON,
                                status=LeaveRequest.Status.APPROVED)
    html = _cells(admin_client)
    assert "is-ghost" in html


@pytest.mark.django_db
def test_a_real_entry_beats_a_ghost(admin_client):
    c = make_clinician("Real", initials="RL")
    _pattern(c, 0, "AM")
    al = make_session_type("Annual Leave", code="AL4", category="ABSENCE")
    make_entry(c, day=MON, part="AM", session_type=al, is_published=True)
    LeaveRequest.objects.create(clinician=c, session_type=al,
                                start_date=MON, end_date=MON,
                                status=LeaveRequest.Status.APPROVED)
    html = _cells(admin_client)
    assert "is-ghost" not in html


@pytest.mark.django_db
def test_warnings_are_admin_only_but_day_notes_are_for_everyone(
    admin_client, gp_client
):
    from rota.models import DayNote
    PracticeSettings.load()
    DayNote.objects.create(day=MON, text="CQC visit")
    make_clinician("Someone", initials="SO")

    admin_html = _cells(admin_client)
    gp_html = _cells(gp_client)

    assert "CQC visit" in admin_html
    assert "CQC visit" in gp_html, "day notes are practice information"
    assert 'class="warn"' in admin_html, "an understaffed day warns an admin"
    assert 'class="warn"' not in gp_html, "warnings are staffing alerts, admin only"


@pytest.mark.django_db
def test_no_ghost_on_a_closed_day_inside_a_leave_range(admin_client):
    """`leave.sessions_affected()` skips days `calendar.is_open()` calls
    closed, so approval correctly writes nothing on a bank holiday. A ghost
    there captions "check the clinician's pattern" about a day where nothing
    is wrong — two of them per full-timer, on every leave request spanning a
    bank holiday or the Christmas closure."""
    c = make_clinician("Holiday", initials="HD")
    _full_pattern(c)
    ClosedDay.objects.create(day=MON + timedelta(days=2), reason="Bank holiday")
    al = make_session_type("Annual Leave", code="ALC", category="ABSENCE")
    LeaveRequest.objects.create(clinician=c, session_type=al,
                                start_date=MON, end_date=MON + timedelta(days=4),
                                status=LeaveRequest.Status.APPROVED)
    chips = _chips(_cells(admin_client))

    for part in ("AM", "PM"):
        assert chips[(c.id, _iso(2), part)] != "is-ghost", (
            f"ghosted the {part} of a closed day, where approval was right "
            f"to write nothing"
        )
    for offset in (0, 1, 3, 4):
        for part in ("AM", "PM"):
            assert chips[(c.id, _iso(offset), part)] == "is-ghost", (
                "the open days around the closure should still ghost"
            )


@pytest.mark.django_db
def test_a_clinician_with_no_pattern_gets_no_ghosts_outside_their_window(
    admin_client
):
    """The no-pattern ghost clause never consulted the date window, so a new
    joiner whose start_date is a month away — and who has no pattern rows yet,
    which is exactly the state a new joiner is in — got a chip on all ten
    sessions of a week they are not employed for."""
    c = make_clinician("Joiner", initials="JO",
                       start_date=MON + timedelta(days=30))
    al = make_session_type("Annual Leave", code="ALJ", category="ABSENCE")
    LeaveRequest.objects.create(clinician=c, session_type=al,
                                start_date=MON, end_date=MON + timedelta(days=4),
                                status=LeaveRequest.Status.APPROVED)
    html = _cells(admin_client)
    assert "is-ghost" not in html, (
        f"ghosted {html.count('is-ghost')} sessions before the clinician's "
        f"start date"
    )
    assert set(_chips(html).values()) == {"is-off"}


@pytest.mark.django_db
def test_a_session_outside_the_contractual_window_renders_blank(admin_client):
    """Named in the spec's own testing list and covered by nothing: "A session
    outside a clinician's start/end window renders blank, identical to a
    non-working session"."""
    c = make_clinician("Leaver", initials="LR", end_date=MON + timedelta(days=1))
    _full_pattern(c)
    chips = _chips(_cells(admin_client))

    assert chips[(c.id, _iso(0), "AM")] == "empty-slot", "inside the window"
    assert chips[(c.id, _iso(1), "PM")] == "empty-slot", "the last day of it"
    for offset in (2, 3, 4):
        for part in ("AM", "PM"):
            assert chips[(c.id, _iso(offset), part)] == "is-off", (
                "a session after end_date should look exactly like a session "
                "the clinician does not work"
            )


@pytest.mark.django_db
def test_the_grid_renders_with_no_open_weekdays(admin_client):
    """`parse_int_list("")` returns [] by design and PracticeSettings.clean()
    accepts a blank value, so `days` can be empty. The leave filter's
    days[-1]/days[0] made that an IndexError and 500'd the main page; master
    rendered an empty grid."""
    settings = PracticeSettings.load()
    PracticeSettings.objects.filter(pk=settings.pk).update(open_weekdays="")
    c = make_clinician("Nobody", initials="NB")
    _full_pattern(c)

    resp = admin_client.get(f"/rota/?week={MON.isoformat()}")
    assert resp.status_code == 200
    assert _chips(resp.content.decode()) == {}, "no open weekday, so no cells"


@pytest.mark.django_db
def test_a_reordered_open_weekdays_does_not_run_the_leave_range_backwards(
    admin_client
):
    """parse_int_list preserves input order, so days[0]/days[-1] are not the
    week's first and last dates. With "4,0,1,2,3" the overlap filter ran
    Friday..Thursday and matched nothing, and the Publish button's end date
    landed before its start."""
    settings = PracticeSettings.load()
    PracticeSettings.objects.filter(pk=settings.pk).update(
        open_weekdays="4,0,1,2,3")
    c = make_clinician("Backwards", initials="BW")
    _full_pattern(c)
    al = make_session_type("Annual Leave", code="ALB", category="ABSENCE")
    LeaveRequest.objects.create(clinician=c, session_type=al,
                                start_date=MON, end_date=MON,
                                status=LeaveRequest.Status.APPROVED)
    html = admin_client.get(f"/rota/?week={MON.isoformat()}").content.decode()

    chips = _chips(html)
    assert chips[(c.id, _iso(0), "AM")] == "is-ghost", (
        "Monday's leave fell outside a backwards start..end filter"
    )
    assert f'name="end" value="{_iso(4)}"' in html, (
        "Publish would post a range ending before it starts, publishing nothing"
    )


@pytest.mark.django_db
def test_the_grid_query_count_does_not_grow_with_clinicians_or_leave(
    admin_client
):
    """The spec promised this: "No new per-cell queries; asserted by a
    query-count test rather than by inspection." What existed measured the
    resolver in isolation — dropping select_related("session_type") from the
    grid's leave prefetch would add a query per approved leave request and
    every test would still pass."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    PracticeSettings.load()
    al = make_session_type("Annual Leave", code="ALN", category="ABSENCE")

    def add(n, tag):
        for i in range(n):
            c = make_clinician(f"Doctor {tag}{i}", initials=f"D{tag}{i}")
            _full_pattern(c)
            LeaveRequest.objects.create(
                clinician=c, session_type=al, start_date=MON,
                end_date=MON + timedelta(days=4),
                status=LeaveRequest.Status.APPROVED)

    def queries():
        with CaptureQueriesContext(connection) as ctx:
            resp = admin_client.get(f"/rota/?week={MON.isoformat()}")
        assert resp.status_code == 200
        return len(ctx)

    add(2, "a")
    queries()               # warm up: session and template lookups
    baseline = queries()
    assert "is-ghost" in admin_client.get(
        f"/rota/?week={MON.isoformat()}").content.decode(), (
        "the leave chips must actually be rendering for this to measure them"
    )

    add(6, "b")
    assert queries() == baseline, (
        "the grid issues more queries with more clinicians and more approved "
        "leave — something is asking per row or per cell"
    )
