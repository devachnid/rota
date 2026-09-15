"""What a grid cell shows, and why.

Cell precedence:
    entry exists                -> the entry
    absence from Breathe        -> a chip with the Breathe code
    works_on                    -> grey: working, nothing allocated
    usual non-working half-day  -> OFF, muted on the sunken ground
    otherwise                   -> blank: closed, or not employed that day
"""

import re
from datetime import date, timedelta

import pytest

from rota.models import ClosedDay, PatternSlot, PracticeSettings
from tests.factories import make_absence, make_clinician, make_entry, make_session_type

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
    r"/rota/cell/(?P<cid>\d+)/(?P<day>\d{4}-\d\d-\d\d)/(?P<part>AM|PM|DAY)/"
    r'.*?<span class="chip(?P<classes>[^"]*)"(?P<rest>[^>]*)>',
    re.S,
)


def _chips(html):
    """{(clinician_id, ISO day, part): the chip's modifier classes, or
    "absence" for a Breathe absence chip.

    Counting classes across the whole page cannot tell `empty-slot` on the
    worked cell from `is-off` on it: swap the two template branches and every
    total is identical. This reads which class landed on which cell.

    An absence chip carries no modifier class of its own — the template
    tells it apart from a real entry with a title ending "— from Breathe" —
    so a cell with an empty class and that title is labelled "absence" here.
    """
    out = {}
    for m in _CELL_RE.finditer(html):
        classes = m["classes"].strip()
        if not classes and "from Breathe" in m["rest"]:
            classes = "absence"
        # A whole day drawn as one chip opens on part DAY; it stands for
        # both halves here, so per-cell assertions read the same either way.
        parts = ("AM", "PM") if m["part"] == "DAY" else (m["part"],)
        for part in parts:
            out[(int(m["cid"]), m["day"], part)] = classes
    return out


def _iso(offset):
    return (MON + timedelta(days=offset)).isoformat()


@pytest.mark.django_db
def test_a_worked_but_unallocated_session_is_grey(admin_client):
    """Per cell, not per page. `"empty-slot" in html` was true of the exact
    inversion this task shipped to fix: one clinician working Monday AM gives
    the page 1 empty-slot and 9 is-off-is-not-working, and swapping the template's two
    branches gives it 9 and 1 — that assertion passes either way."""
    c = make_clinician("Grey", initials="GY")
    _pattern(c, 0, "AM")
    chips = _chips(_cells(admin_client))
    assert chips[(c.id, _iso(0), "AM")] == "empty-slot", (
        "the worked, unallocated session should carry the grey class"
    )
    assert chips[(c.id, _iso(0), "PM")] == "is-off is-not-working"
    assert chips[(c.id, _iso(1), "AM")] == "is-off is-not-working"
    assert sum(1 for v in chips.values() if v == "empty-slot") == 8, (
        "only the one worked session should be grey -- and the window shows "
        "eight weeks, so exactly one Monday AM per week and nothing else"
    )


@pytest.mark.django_db
def test_a_non_working_session_reads_off(admin_client):
    """A part-timer's day off used to be blank, the same as a closed day or
    a session outside someone's dates, and users read blank as "not filled
    yet". It now says OFF; the other blanks stay blank."""
    c = make_clinician("Blank", initials="BL")
    _pattern(c, 0, "AM", works=False)
    html = _cells(admin_client)
    chips = _chips(html)
    assert chips[(c.id, _iso(0), "AM")] == "is-off is-not-working"
    assert set(chips.values()) == {"is-off is-not-working"}, (
        "this clinician works nothing, so nothing should be grey"
    )
    assert 'title="Not a working session">OFF<' in html
    assert "unavail" not in html, "the old class is gone"


@pytest.mark.django_db
def test_a_closed_day_stays_blank_for_a_non_working_session(admin_client):
    c = make_clinician("Closed", initials="CD")
    _pattern(c, 0, "AM", works=False)
    ClosedDay.objects.create(day=MON, reason="Bank holiday")
    chips = _chips(_cells(admin_client))
    assert chips[(c.id, _iso(0), "AM")] == "is-off"


@pytest.mark.django_db
def test_approved_leave_ghosts_on_a_session_the_clinician_works(admin_client):
    """The Breathe overlay should have written an entry here and did not —
    the chip is the signal that something went wrong."""
    c = make_clinician("Ghosted", initials="GH")
    _pattern(c, 0, "AM")
    make_absence(c, MON)
    html = _cells(admin_client)
    assert 'title="Holiday — from Breathe"' in html
    assert "AL" in html


@pytest.mark.django_db
def test_a_part_timer_gets_no_ghost_on_their_non_working_days(admin_client):
    """The noise case. Showing the chip on every session a leave span covers
    would put chips on every part-timer's days off, every time they took
    leave."""
    c = make_clinician("Parttime", initials="PT")
    _pattern(c, 0, "AM")            # works Monday AM only
    _pattern(c, 0, "PM", works=False)
    make_absence(c, MON, MON + timedelta(days=4))
    html = _cells(admin_client)
    n = html.count("from Breathe")
    assert n == 1, f"expected one absence chip (Monday AM), got {n}"


@pytest.mark.django_db
def test_a_half_day_absence_only_ghosts_the_half_it_covers(admin_client):
    """A part-blind mutation of `if part in parts_off(...)` (e.g. checking
    only the span's dates) would put the chip on both parts of a half-day
    absence. A PM half-start on a single day should leave Monday AM clear
    and put the chip on Monday PM alone."""
    c = make_clinician("Halfday", initials="HF")
    _full_pattern(c)
    make_absence(c, MON, MON, half_start=True, half_start_am_pm="PM")
    chips = _chips(_cells(admin_client))
    assert chips[(c.id, _iso(0), "AM")] != "absence", (
        "the morning is not covered by a PM half-start absence"
    )
    assert chips[(c.id, _iso(0), "PM")] == "absence", (
        "the afternoon should still show the absence chip"
    )


@pytest.mark.django_db
def test_a_clinician_with_no_pattern_at_all_gets_ghosts(admin_client):
    """The original complaint: leave recorded, nothing anywhere."""
    c = make_clinician("Nopattern", initials="NP")
    make_absence(c, MON)
    html = _cells(admin_client)
    assert 'title="Holiday — from Breathe"' in html


@pytest.mark.django_db
def test_a_real_entry_beats_a_ghost(admin_client):
    c = make_clinician("Real", initials="RL")
    _pattern(c, 0, "AM")
    al = make_session_type("Annual Leave", code="AL4", category="ABSENCE")
    make_entry(c, day=MON, part="AM", session_type=al, is_published=True)
    make_absence(c, MON)
    html = _cells(admin_client)
    chips = _chips(html)
    assert chips[(c.id, _iso(0), "AM")] == "", (
        "the AL entry renders as a plain published chip — not the Breathe "
        "absence chip, and not ringed as a clash: an absence entry over "
        "Breathe leave is agreement"
    )
    assert "On Breathe leave" not in html


@pytest.mark.django_db
def test_an_unmapped_absence_renders_no_chip_but_does_not_500(admin_client):
    """leave_type() returns None for an absence whose mapping row is
    missing, so cell_state has nothing to render — but on_leave() (which the
    fill engine depends on) does not go through the mapping, and resolving a
    chip that isn't there must not raise."""
    from rota.models import BreatheLeaveMapping

    c = make_clinician("Unmapped", initials="UM")
    _pattern(c, 0, "AM")
    make_absence(c, MON, kind="sickness")
    BreatheLeaveMapping.objects.filter(kind="sickness", reason="").delete()

    resp = admin_client.get(f"/rota/?week={MON.isoformat()}")
    assert resp.status_code == 200
    chips = _chips(resp.content.decode())
    assert chips[(c.id, _iso(0), "AM")] != "absence"


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
    """The sync does not write absences for closed days any differently, but
    cell_state suppresses the chip there — a bank holiday inside a leave
    range correctly has no entry, and a chip there captions "check the
    clinician's pattern" about a day where nothing is wrong — two of them
    per full-timer, on every leave span crossing a bank holiday or the
    Christmas closure."""
    c = make_clinician("Holiday", initials="HD")
    _full_pattern(c)
    ClosedDay.objects.create(day=MON + timedelta(days=2), reason="Bank holiday")
    make_absence(c, MON, MON + timedelta(days=4))
    chips = _chips(_cells(admin_client))

    for part in ("AM", "PM"):
        assert chips[(c.id, _iso(2), part)] != "absence", (
            f"showed the {part} absence chip on a closed day, where nothing "
            f"should render"
        )
    for offset in (0, 1, 3, 4):
        for part in ("AM", "PM"):
            assert chips[(c.id, _iso(offset), part)] == "absence", (
                "the open days around the closure should still show the "
                "absence chip"
            )


@pytest.mark.django_db
def test_a_clinician_with_no_pattern_gets_no_ghosts_outside_their_window(
    admin_client
):
    """The no-pattern chip clause never consulted the date window, so a new
    joiner whose start_date is a month away — and who has no pattern rows yet,
    which is exactly the state a new joiner is in — got a chip on all ten
    sessions of a week they are not employed for. The eight-week window
    reaches past their start date, so they do have a row here; every session
    of it must read blank and the absence must not surface anywhere."""
    c = make_clinician("Joiner", initials="JO",
                       start_date=MON + timedelta(days=30))
    make_absence(c, MON, MON + timedelta(days=4))
    html = _cells(admin_client)
    n = html.count("from Breathe")
    assert n == 0, f"showed {n} absence chips before the clinician's start date"
    assert set(_chips(html).values()) == {"is-off"}, (
        "with no pattern rows and no entries, every session reads blank — "
        "before the start date and after it"
    )


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
    accepts a blank value, so `days` can be empty. The absence filter's
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
    make_absence(c, MON)
    # Publish now sits in the week's header cell and renders only where
    # there are drafts, so the week needs one for its end date to be read.
    # Tuesday, to leave Monday AM's absence chip alone.
    make_entry(c, day=MON + timedelta(days=1), part="AM", is_published=False,
               session_type=make_session_type("Routine", code="ROUT"))
    html = admin_client.get(f"/rota/?week={MON.isoformat()}").content.decode()

    chips = _chips(html)
    assert chips[(c.id, _iso(0), "AM")] == "absence", (
        "Monday's absence fell outside a backwards start..end filter"
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
    resolver in isolation — resolving each absence's session type by
    querying per row instead of through the pre-fetched
    BreatheLeaveMapping.as_dict() would add a query per absence and every
    test would still pass."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    PracticeSettings.load()

    def add(n, tag):
        for i in range(n):
            c = make_clinician(f"Doctor {tag}{i}", initials=f"D{tag}{i}")
            _full_pattern(c)
            make_absence(c, MON, MON + timedelta(days=4))

    def queries():
        with CaptureQueriesContext(connection) as ctx:
            resp = admin_client.get(f"/rota/?week={MON.isoformat()}")
        assert resp.status_code == 200
        return len(ctx)

    add(2, "a")
    queries()               # warm up: session and template lookups
    baseline = queries()
    assert "from Breathe" in admin_client.get(
        f"/rota/?week={MON.isoformat()}").content.decode(), (
        "the absence chips must actually be rendering for this to measure them"
    )

    add(6, "b")
    assert queries() == baseline, (
        "the grid issues more queries with more clinicians and more leave — "
        "something is asking per row or per cell"
    )


# ------------------------------------------------------------- clashes ---


def _rostered_on_leave(name, initials, **absence_kw):
    c = make_clinician(name, initials=initials)
    _pattern(c, 0, "AM")
    make_entry(c, day=MON, part="AM",
               session_type=make_session_type("Routine", code="ROUT"),
               **{k: v for k, v in absence_kw.items() if k == "is_published"})
    make_absence(c, MON, **{k: v for k, v in absence_kw.items() if k != "is_published"})
    return c


@pytest.mark.django_db
def test_a_rostered_session_over_breathe_leave_is_ringed_for_everyone(
        admin_client, gp_client):
    """Tom's decision: the marker and the kind of leave are for every user
    who can see the cell. The header line stays admin-only."""
    c = _rostered_on_leave("Clash", "CL")
    for client in (admin_client, gp_client):
        html = _cells(client)
        assert "is-clash" in _chips(html)[(c.id, _iso(0), "AM")] if client is admin_client \
            else 'class="chip is-clash"' in html
        assert "On Breathe leave: Holiday" in html


@pytest.mark.django_db
def test_a_draft_clash_is_invisible_to_a_gp(admin_client, gp_client):
    c = _rostered_on_leave("Draft", "DR", is_published=False)
    assert "is-clash" in _chips(_cells(admin_client))[(c.id, _iso(0), "AM")]
    gp_html = _cells(gp_client)
    assert "is-clash" not in gp_html
    assert "On Breathe leave" not in gp_html


@pytest.mark.django_db
def test_the_absence_tooltip_names_the_kind_and_reason(admin_client):
    for name, initials, kw in (
            ("Holly Day", "HD", {}),
            ("Sid Sick", "SS", {"kind": "sickness"}),
            ("Jo Jury", "JJ", {"kind": "other", "reason": "Jury service"})):
        c = make_clinician(name, initials=initials)
        _pattern(c, 0, "AM")
        make_absence(c, MON, **kw)
    html = _cells(admin_client)
    assert 'title="Holiday — from Breathe"' in html
    assert 'title="Sick — from Breathe"' in html
    assert 'title="Other leave: Jury service — from Breathe"' in html


# --------------------------------------------------------------- notes ---


@pytest.mark.django_db
def test_a_note_marks_its_chip_and_a_fill_reason_alone_does_not(admin_client):
    """A note is something a person wrote; fill_reason is the engine's
    diagnostic. Only the first earns a dot."""
    rout = make_session_type("Routine", code="ROUT")
    noted = make_clinician("Noted", initials="NT")
    _pattern(noted, 0, "AM")
    make_entry(noted, day=MON, part="AM", session_type=rout, note="Bring the laptop")
    plain = make_clinician("Plain", initials="PL")
    _pattern(plain, 0, "AM")
    make_entry(plain, day=MON, part="AM", session_type=rout, fill_reason="default fill")
    chips = _chips(_cells(admin_client))
    assert "has-note" in chips[(noted.id, _iso(0), "AM")]
    assert "has-note" not in chips[(plain.id, _iso(0), "AM")]


@pytest.mark.django_db
def test_a_whole_day_off_is_one_chip_across_both_columns(admin_client):
    """OFF AM beside OFF PM read as two chips per day off, twenty rows of
    them on staging. A whole day off is one chip, like a matching pair of
    sessions; a day with one worked half keeps two cells."""
    c = make_clinician("Dayoff", initials="DO")
    _pattern(c, 0, "AM")            # works Monday AM only
    html = _cells(admin_client)
    mon = html.index(f'hx-get="/rota/cell/{c.id}/{_iso(0)}/AM/"')
    assert 'colspan="2"' not in html[html.rindex("<td", 0, mon):mon]
    tue = html.index(f'hx-get="/rota/cell/{c.id}/{_iso(1)}/DAY/"')
    assert 'colspan="2"' in html[html.rindex("<td", 0, tue):tue]
    assert f'/rota/cell/{c.id}/{_iso(1)}/AM/' not in html
    chips = _chips(html)
    assert chips[(c.id, _iso(1), "AM")] == chips[(c.id, _iso(1), "PM")] == "is-off is-not-working"
