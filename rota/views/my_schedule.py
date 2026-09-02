from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rota.models import (BreatheAbsence, BreatheLeaveMapping, ClosedDay,
                         PatternSlot, PracticeSettings, RotaEntry,
                         SessionType, SwapRequest)
from rota.services import availability
from rota.services.cells import cell_state

WEEKS_SHOWN = 4


def _is_leave_cell(cell):
    """Whether one cell counts toward "on leave": a Breathe absence, or (for
    history predating the overlay) an absence-category entry. Off cells
    (nothing expected there at all) never count — they are dashes, not
    leave."""
    absence = SessionType.Category.ABSENCE
    return cell["absence"] is not None or (
        cell["entry"] is not None
        and cell["entry"].session_type.category == absence)


def _blocks(clinician, today, open_weekdays, closed, entries_by, resolver):
    """Four Monday-based blocks of open days, with a count for each.

    A day is shown if the surgery is open on it, OR the clinician has an
    entry on it. A closed day (or a weekday outside open_weekdays) with
    nothing on it stays hidden: that is not your day off, and a weekend is
    not either. But a closed day, or an otherwise-non-open weekday, WITH a
    published entry is shown anyway: hiding a real session from the person
    rostered to work it is worse than the tidiness of omitting an empty row.

    am_cell/pm_cell go through cell_state(), the same as the grid and the
    day view: Breathe is the source of leave now, and a GP must see their
    own on their own schedule.
    """
    monday = today - timedelta(days=today.weekday())
    blocks = []
    for index in range(WEEKS_SHOWN):
        start = monday + timedelta(weeks=index)
        days = []
        for offset in range(7):
            day = start + timedelta(days=offset)
            am, pm = entries_by.get((day, "AM")), entries_by.get((day, "PM"))
            is_open = day.weekday() in open_weekdays and day not in closed
            am_cell = cell_state(clinician.id, day, "AM", entry=am,
                                 resolver=resolver, closed=not is_open)
            pm_cell = cell_state(clinician.id, day, "PM", entry=pm,
                                 resolver=resolver, closed=not is_open)
            # No absence clause here: cell_state suppresses absence on a
            # closed day, so a bank holiday inside a leave span is omitted
            # like any other closed day — which is the decision for this
            # page.
            if not (is_open or am_cell["entry"] or pm_cell["entry"]):
                continue
            worked_cells = [c for c in (am_cell, pm_cell) if not c["off"]]
            is_leave = bool(worked_cells) and all(
                _is_leave_cell(c) for c in worked_cells)
            days.append({"day": day, "am": am, "pm": pm,
                        "am_cell": am_cell, "pm_cell": pm_cell,
                        "is_leave": is_leave})
        worked_cells = [c for row in days
                       for c in (row["am_cell"], row["pm_cell"])
                       if not c["off"]]
        sessions = [e for row in days
                    for e in (row["am"], row["pm"]) if e is not None]
        if not days:
            # Nothing to count — "Surgery closed all week" is the body's
            # own words for this; a "0 sessions" label beside it would
            # read as an ordinary week where nothing happened to be
            # booked, which is not what happened.
            label = ""
        elif worked_cells and all(_is_leave_cell(c) for c in worked_cells):
            label = "On leave all week"
        else:
            n = len(sessions)
            label = f"{n} session" if n == 1 else f"{n} sessions"
        blocks.append({
            "heading": "This week" if index == 0
                       else f"Week of {start.strftime('%-d %b')}",
            "count_label": label,
            "days": days,
        })
    return blocks


@login_required
def my_schedule(request):
    clinician = getattr(request.user, "clinician", None)
    if clinician is None:
        return render(request, "rota/my_schedule.html", {"clinician": None})

    today = date.today()
    settings = PracticeSettings.load()
    open_weekdays = set(settings.open_weekday_list())
    monday = today - timedelta(days=today.weekday())
    last = monday + timedelta(weeks=WEEKS_SHOWN) - timedelta(days=1)

    closed = set(ClosedDay.objects.filter(
        day__range=(monday, last)).values_list("day", flat=True))

    entries = RotaEntry.objects.filter(
        clinician=clinician, is_published=True, day__range=(monday, last),
    ).select_related("session_type", "site")
    entries_by = {(e.day, e.part): e for e in entries}

    pattern_rows = list(PatternSlot.objects.filter(clinician=clinician))
    absences = BreatheAbsence.objects.filter(
        clinician=clinician, start_date__lte=last, end_date__gte=monday)
    resolver = availability.AvailabilityResolver(
        pattern_rows, [clinician], absences, BreatheLeaveMapping.as_dict())

    # Same rule as _blocks(): a session the clinician actually has, or an
    # absence covering it, beats the closure. Checked first and
    # unconditionally, so an entry (or a Breathe absence) on a closed or
    # non-open "today" still reports "working" and renders, rather than
    # telling a GP the surgery is shut on a day they have a session or
    # leave sitting against them. "closed" and "not_in" are reserved for
    # the no-entry, no-absence cases below.
    #
    # Unlike _blocks()'s inclusion rule, this absence clause is not dead:
    # there is no third "already true" disjunct here keyed off today_closed
    # the way is_open is there, so on an open today with a half-day Breathe
    # absence and no RotaEntry, the absence clause is the only route to
    # "working" — dropping it reads a GP as "not_in" on a day they are, in
    # fact, half in.
    today_closed = today in closed or today.weekday() not in open_weekdays
    today_am_cell = cell_state(clinician.id, today, "AM",
                               entry=entries_by.get((today, "AM")),
                               resolver=resolver, closed=today_closed)
    today_pm_cell = cell_state(clinician.id, today, "PM",
                               entry=entries_by.get((today, "PM")),
                               resolver=resolver, closed=today_closed)
    if (today_am_cell["entry"] or today_pm_cell["entry"]
            or today_am_cell["absence"] or today_pm_cell["absence"]):
        today_state = "working"
    elif today_closed:
        today_state = "closed"
    else:
        today_state = "not_in"

    return render(request, "rota/my_schedule.html", {
        "clinician": clinician,
        "today": today,
        "today_state": today_state,
        "today_cells": [today_am_cell, today_pm_cell],
        "today_closed_reason": next(
            (cd.reason for cd in ClosedDay.objects.filter(day=today)), ""),
        "weeks": _blocks(clinician, today, open_weekdays, closed, entries_by,
                         resolver),
        "my_swaps": list(SwapRequest.objects.filter(
            proposer=clinician
        ).exclude(status=SwapRequest.Status.DECLINED
                  ).select_related("colleague")[:10]),
        "to_accept": SwapRequest.objects.filter(
            colleague=clinician, status=SwapRequest.Status.PROPOSED
        ).select_related("proposer"),
    })
