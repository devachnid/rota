"""The day view: who is on, and nothing about whether that is enough.

The screen deliberately carries no coverage, staffing or group warnings for
either role. A GP reading a roster can judge cover themselves, and an app
that says "covered" when it is not is worse than one that says nothing.
"""

from datetime import date

import pytest

from rota.models import PatternSlot, PracticeSettings
from tests.factories import (make_absence, make_clinician, make_entry,
                             make_pattern, make_session_type, make_site)

pytestmark = pytest.mark.django_db

TUE = date(2026, 9, 8)


def _html(client, day=TUE):
    PracticeSettings.load()
    return client.get(f"/rota/day/{day.isoformat()}/").content.decode()


def _tbody(html, after=None):
    """The contents of one <tbody>...</tbody>.

    The roster table's tbody is the first one on the page (the pinned block
    above it, when present, is a <div>, not a table). The on-leave table's
    tbody is the first one after the "On leave" heading. Slicing this way —
    rather than checking string presence anywhere in the page — is what lets
    a test tell "in the roster" apart from "in the on-leave group": both
    groups can render the same clinician name and chip code, just under
    different headings.
    """
    if after is not None:
        html = html[html.index(after):]
    start = html.index("<tbody>")
    end = html.index("</tbody>", start)
    return html[start:end]


def _roster_tbody(html):
    """Extract the roster table's tbody by identifying it via its caption.

    Both the roster and the on-leave table carry a <thead> now (item 6:
    screen readers need column headers on both, not just the roster), so a
    "the only table with a <thead>" check no longer tells them apart — and
    would have silently started reading the wrong table's tbody instead of
    failing loudly. The caption text is unique to each table regardless of
    document order, which a <thead>-position check never was.
    """
    return _tbody(html, after="Who is working")


def _on_leave_tbody(html):
    return _tbody(html, after="On leave")


def test_a_clinician_working_the_day_appears_with_both_parts(gp_client, gp_user):
    c = make_clinician("Emma Hall", user=gp_user)
    make_pattern(c)
    rout = make_session_type("Routine", code="ROUT")
    make_entry(c, day=TUE, part="AM", session_type=rout)
    make_entry(c, day=TUE, part="PM", session_type=rout)
    html = _html(gp_client)
    assert "Emma Hall" in html
    assert html.count("ROUT") >= 2


def test_a_chip_with_a_site_carries_the_site_marker(gp_client, gp_user):
    """Named in the spec: the site rides inside the chip on .site-marker
    rather than a column of its own."""
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Owen Priestley")
    make_pattern(c)
    site = make_site("Branch Surgery")
    make_entry(c, day=TUE, part="AM",
               session_type=make_session_type("Routine", code="ROUT"),
               site=site)
    roster = _roster_tbody(_html(gp_client))
    assert 'class="site-marker"' in roster
    assert ">B<" in roster  # the site name's first letter


def test_a_companion_group_entry_shows_the_partners_name(gp_client, gp_user):
    """Named in the spec: .day-partner carries the companion's name for a
    half of a companion_group pair."""
    import uuid
    make_clinician("Viewer", user=gp_user)
    a = make_clinician("Priya Anand")
    b = make_clinician("Rohan Bakshi")
    make_pattern(a)
    make_pattern(b)
    rout = make_session_type("Routine", code="ROUT")
    group = uuid.uuid4()
    make_entry(a, day=TUE, part="AM", session_type=rout, companion_group=group)
    make_entry(b, day=TUE, part="AM", session_type=rout, companion_group=group)
    roster = _roster_tbody(_html(gp_client))
    assert "day-partner" in roster
    assert "with Rohan Bakshi" in roster
    assert "with Priya Anand" in roster


def test_a_clinician_on_leave_all_day_is_in_the_leave_group_not_the_roster(
        gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Anwer Al-Hasani")
    make_pattern(c)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    make_entry(c, day=TUE, part="AM", session_type=al)
    make_entry(c, day=TUE, part="PM", session_type=al)
    html = _html(gp_client)
    # Table membership, not string presence: the same name and "On leave"
    # heading text would both appear even if the row landed in the wrong
    # table, which is exactly the bug this test exists to catch.
    assert "Anwer Al-Hasani" not in _roster_tbody(html)
    assert "Anwer Al-Hasani" in _on_leave_tbody(html)


def test_a_clinician_on_breathe_leave_all_day_shows_the_chip_in_the_leave_group(
        gp_client, gp_user):
    """The on-leave table has its own cell markup, separate from the
    roster's — it must render the overlay chip too, not just fall through to
    the dash it uses for "nothing recorded"."""
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Beatrice Okafor")
    make_pattern(c)
    make_absence(c, TUE)
    html = _html(gp_client)
    assert "Beatrice Okafor" in _on_leave_tbody(html)
    assert "from Breathe" in _on_leave_tbody(html)


def test_half_a_day_of_leave_keeps_the_clinician_in_the_roster(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Esther Lomas")
    make_pattern(c)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    rout = make_session_type("Routine", code="ROUT")
    make_entry(c, day=TUE, part="AM", session_type=al)
    make_entry(c, day=TUE, part="PM", session_type=rout)
    html = _html(gp_client)
    assert "Esther Lomas" in _roster_tbody(html)
    assert "ROUT" in _roster_tbody(html)
    # Nobody else is on leave in this fixture, so if she were misclassified
    # the "On leave" table would appear at all (and hold her row) — check
    # both, so this doesn't just pass because the table happens to exist for
    # another reason.
    assert "On leave" not in html


def test_absence_in_one_part_and_no_entry_at_all_in_the_other_is_roster_not_leave(
        gp_client, gp_user):
    """A full-timer with an absence entry in AM and nothing recorded for PM
    is off for half the day and unallocated for the other half — not "on
    leave all day". Unlike the fixture above (which pairs the absence entry
    with a working entry), this one leaves the other part with no entry at
    all, which is the shape that `all()` over a one-element dict got wrong."""
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Priya Chandra")
    make_pattern(c)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    make_entry(c, day=TUE, part="AM", session_type=al)
    html = _html(gp_client)
    assert "Priya Chandra" in _roster_tbody(html)
    assert "On leave" not in html


def test_a_clinician_with_no_pattern_and_approved_leave_is_a_ghost_in_the_roster(
        gp_client, gp_user):
    """cell_state ghosts a leave chip for a clinician with no PatternSlot
    rows at all — nothing else would ever render for them otherwise, and
    the grid shows exactly this ghost. Bucketing on `cell["off"]` alone put
    this clinician on the "Not in Tuesdays" line instead: off is True (no
    entry, works_on() False with no pattern), so the old condition
    `mine or any(not cell["off"] for cell in cells)` was False. That both
    dropped the admin integrity warning the ghost carries and asserted a
    lie — that they do not work Tuesdays — when the truth is nobody has
    entered their pattern yet."""
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Locum Newcomer")  # deliberately: no make_pattern()
    make_absence(c, TUE)
    html = _html(gp_client)
    assert "Locum Newcomer" in _roster_tbody(html)
    assert "from Breathe" in _roster_tbody(html)
    not_in_line = html[html.index('class="day-not-in"'):]
    assert "Locum Newcomer" not in not_in_line


def test_someone_who_does_not_work_that_day_is_on_the_not_in_line(
        gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Nesreen Mayoub")
    make_pattern(c, weekdays=(0,))  # Mondays only; TUE is a Tuesday
    html = _html(gp_client)
    assert "Not in" in html and "Nesreen Mayoub" in html


def test_a_gp_sees_no_staffing_warnings(gp_client, gp_user):
    """The week grid warns. This screen never does, for either role."""
    make_clinician("Viewer", user=gp_user)
    html = _html(gp_client)
    for phrase in ("clinical GP", "No Duty cover", "in (AM)"):
        assert phrase not in html


def test_an_admin_sees_no_staffing_warnings_either(admin_client):
    html = _html(admin_client)
    for phrase in ("clinical GP", "No Duty cover", "in (AM)"):
        assert phrase not in html


def test_a_gp_does_not_see_unpublished_entries(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Harri Davies")
    make_pattern(c)
    draft = make_session_type("Vasectomy", code="VAS")
    make_entry(c, day=TUE, part="AM", session_type=draft, is_published=False)
    assert "VAS" not in _html(gp_client)


def test_an_admin_does_see_unpublished_entries(admin_client):
    c = make_clinician("Harri Davies")
    make_pattern(c)
    draft = make_session_type("Vasectomy", code="VAS")
    make_entry(c, day=TUE, part="AM", session_type=draft, is_published=False)
    assert "VAS" in _html(admin_client)


def test_a_bare_day_url_renders_today(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    PracticeSettings.load()
    resp = gp_client.get("/rota/day/")
    assert resp.status_code == 200
    # A bare day-of-month number ("8") appears in plenty of markup that has
    # nothing to do with today's date. The header's full formatted date is
    # what the page actually promises to show, so assert that instead — a
    # test that would pass against a blank page is not a test.
    assert date.today().strftime("%-d %b") in resp.content.decode()


def test_a_malformed_date_falls_back_to_today_like_the_grid_does(
        gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    PracticeSettings.load()
    resp = gp_client.get("/rota/day/not-a-date/")
    assert resp.status_code == 200


def test_the_day_note_is_shown_to_everyone(gp_client, gp_user):
    from rota.models import DayNote
    make_clinician("Viewer", user=gp_user)
    DayNote.objects.create(day=TUE, text="Flu clinic in the back room")
    assert "Flu clinic in the back room" in _html(gp_client)


# --------------------------------------------------------------- pinned ---

def test_a_pinned_type_appears_above_the_roster(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Amjad Mahmood")
    make_pattern(c)
    duty = make_session_type("Duty", code="DUTY", pin_on_day_view=True)
    make_entry(c, day=TUE, part="AM", session_type=duty)
    html = _html(gp_client)
    assert html.index("day-pinned") < html.index("day-roster")


def test_no_pinned_types_means_no_block_at_all(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Emma Hall")
    make_pattern(c)
    make_entry(c, day=TUE, part="AM",
               session_type=make_session_type("Routine", code="ROUT"))
    assert "day-pinned" not in _html(gp_client)


def test_a_pinned_type_with_nobody_on_it_shows_no_block(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    make_session_type("Duty", code="DUTY", pin_on_day_view=True)
    assert "day-pinned" not in _html(gp_client)


def test_a_clinician_past_their_end_date_with_a_stray_pinned_entry_appears_nowhere(
        gp_client, gp_user):
    """The roster loop skips anyone failing resolver.in_service(); the pinned
    block must apply the same test. Otherwise a clinician whose end_date has
    passed but who still has a leftover entry for a pinned session type shows
    up in the pinned block while correctly appearing in none of
    roster / on-leave / not-in."""
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Fatima Iqbal", end_date=date(2026, 9, 1))
    make_pattern(c)
    duty = make_session_type("Duty", code="DUTY", pin_on_day_view=True)
    make_entry(c, day=TUE, part="AM", session_type=duty)  # TUE is after end_date
    html = _html(gp_client)
    assert "Fatima Iqbal" not in html


# --------------------------------------------------------------- closed ---

def test_a_closed_day_says_so_and_shows_no_roster(gp_client, gp_user):
    from rota.models import ClosedDay
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Emma Hall")
    make_pattern(c)
    ClosedDay.objects.create(day=TUE, reason="August bank holiday")
    html = _html(gp_client)
    assert "August bank holiday" in html
    assert "day-roster" not in html


def test_a_closed_day_with_a_real_entry_still_shows_the_roster(gp_client, gp_user):
    """The bug this fix exists for: a ClosedDay plus a published Routine
    entry used to make the day view render the closure sentence and
    nothing else. This is the one screen built to answer "who is on
    today" — it must be able to answer that on a bank holiday too, when
    someone really is rostered on."""
    from rota.models import ClosedDay
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Farida Chowdhury")
    make_pattern(c)
    ClosedDay.objects.create(day=TUE, reason="August bank holiday")
    make_entry(c, day=TUE, part="AM",
               session_type=make_session_type("Routine", code="ROUT"))
    html = _html(gp_client)
    assert "August bank holiday" in html
    assert "day-roster" in html
    assert "Farida Chowdhury" in _roster_tbody(html)
    assert "ROUT" in _roster_tbody(html)


def test_a_closed_day_with_only_a_leave_entry_still_shows_the_leave_group(
        gp_client, gp_user):
    """The same rule, exercised through the on-leave branch rather than the
    roster: an absence entry on a closed day is still an entry, and the
    body must render for it too."""
    from rota.models import ClosedDay
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Grzegorz Nowak")
    make_pattern(c)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    ClosedDay.objects.create(day=TUE, reason="Training day")
    make_entry(c, day=TUE, part="AM", session_type=al)
    make_entry(c, day=TUE, part="PM", session_type=al)
    html = _html(gp_client)
    assert "Training day" in html
    assert "Grzegorz Nowak" in _on_leave_tbody(html)


def test_a_closed_day_still_shows_its_day_note(gp_client, gp_user):
    from rota.models import ClosedDay, DayNote
    make_clinician("Viewer", user=gp_user)
    ClosedDay.objects.create(day=TUE, reason="Bank holiday")
    DayNote.objects.create(day=TUE, text="Emergency line diverted")
    assert "Emergency line diverted" in _html(gp_client)


def test_a_weekend_is_closed_without_a_closedday_row(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    saturday = date(2026, 9, 12)
    assert saturday.weekday() == 5
    assert "day-roster" not in _html(gp_client, day=saturday)


# --------------------------------------------------------- header count ---

def test_the_count_line_matches_the_rendered_roster_and_leave_groups(
        gp_client, gp_user):
    """Named in the spec: "<n> in · <m> on leave". n is the roster's row
    count, m the on-leave group's — not the size of the full clinician
    list, which is what a header computed before the split would show."""
    make_clinician("Viewer", user=gp_user)
    working = make_clinician("Amara Osei")
    make_pattern(working)
    make_entry(working, day=TUE, part="AM",
               session_type=make_session_type("Routine", code="ROUT"))
    on_leave = make_clinician("Baljit Bhatt")
    make_pattern(on_leave)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    make_entry(on_leave, day=TUE, part="AM", session_type=al)
    make_entry(on_leave, day=TUE, part="PM", session_type=al)
    html = _html(gp_client)
    # Viewer has no pattern and is filed under "Not in", so it must not be
    # counted in either figure — this is the assertion a header wired to
    # len(active) instead of len(roster) would fail.
    assert "1 in &middot; 1 on leave" in html


def test_the_count_line_is_suppressed_when_a_closed_day_has_nothing_to_count(
        gp_client, gp_user):
    """The body is suppressed for a closed day with no entries (the pinned
    test_a_closed_day_says_so_and_shows_no_roster case); the count line
    above it must be suppressed along with it rather than reading
    "0 in · 0 on leave" over a body that was refused."""
    from rota.models import ClosedDay
    make_clinician("Viewer", user=gp_user)
    ClosedDay.objects.create(day=TUE, reason="Bank holiday")
    assert "day-count" not in _html(gp_client)


def test_the_count_line_still_shows_when_a_closed_day_has_entries(
        gp_client, gp_user):
    from rota.models import ClosedDay
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Priti Patel")
    make_pattern(c)
    ClosedDay.objects.create(day=TUE, reason="Training day")
    make_entry(c, day=TUE, part="AM",
               session_type=make_session_type("Routine", code="ROUT"))
    html = _html(gp_client)
    assert "day-count" in html
    assert "1 in &middot; 0 on leave" in html


# -------------------------------------------------------------- on leave ---

def test_the_on_leave_table_has_column_headers_and_a_caption(gp_client, gp_user):
    """The roster table already has both (WCAG: a screen-reader user needs
    column headers to tell AM from PM, not just the row's clinician name).
    The on-leave table carried neither."""
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Nadia Farooqi")
    make_pattern(c)
    al = make_session_type("Annual Leave", code="AL", category="ABSENCE")
    make_entry(c, day=TUE, part="AM", session_type=al)
    make_entry(c, day=TUE, part="PM", session_type=al)
    html = _html(gp_client)
    after_heading = html[html.index('class="day-group"'):]
    assert "<thead>" in after_heading
    assert "<caption" in after_heading


# -------------------------------------------------------------- steppers ---

def test_the_next_link_from_friday_skips_the_weekend(gp_client, gp_user):
    make_clinician("Viewer", user=gp_user)
    friday = date(2026, 9, 11)
    assert friday.weekday() == 4
    html = _html(gp_client, day=friday)
    assert "/rota/day/2026-09-14/" in html


def test_the_stepper_skips_a_closed_day(gp_client, gp_user):
    from rota.models import ClosedDay
    make_clinician("Viewer", user=gp_user)
    ClosedDay.objects.create(day=date(2026, 9, 9), reason="Training")
    html = _html(gp_client, day=TUE)  # Tue 8th; Wed 9th is closed
    assert "/rota/day/2026-09-10/" in html


def test_the_stepper_terminates_when_the_practice_has_no_open_weekdays(
        gp_client, gp_user):
    """open_weekdays = '' parses to [] and clean() accepts it. A stepper that
    walks forward looking for an open day would never find one."""
    make_clinician("Viewer", user=gp_user)
    s = PracticeSettings.load()
    s.open_weekdays = ""
    s.save()
    resp = gp_client.get(f"/rota/day/{TUE.isoformat()}/")
    assert resp.status_code == 200


def test_a_clash_files_under_on_leave_with_the_marker(gp_client, gp_user):
    """Breathe says they are off, so the section says so; the ringed chip
    is what makes the session the visible anomaly."""
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Cara Clash")
    make_pattern(c)
    rout = make_session_type("Routine", code="ROUT")
    make_entry(c, day=TUE, part="AM", session_type=rout)
    make_entry(c, day=TUE, part="PM", session_type=rout)
    make_absence(c, TUE)
    html = _html(gp_client)
    leave = _on_leave_tbody(html)
    assert "Cara Clash" in leave
    assert "is-clash" in leave
    assert "On Breathe leave: Holiday" in leave
    assert "0 in &middot; 1 on leave" in html


def test_a_note_is_printed_under_the_chip(gp_client, gp_user):
    """No hover on a phone, and the day view is the phone screen."""
    make_clinician("Viewer", user=gp_user)
    c = make_clinician("Nora Note")
    make_pattern(c)
    make_entry(c, day=TUE, part="AM", note="Bring the laptop",
               session_type=make_session_type("Routine", code="ROUT"))
    roster = _roster_tbody(_html(gp_client))
    assert "has-note" in roster
    assert 'class="day-note-text">Bring the laptop<' in roster
