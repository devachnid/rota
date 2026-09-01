from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rota.models import (ClosedDay, LeaveRequest, PracticeSettings, RotaEntry,
                         SessionType, SwapRequest)
from rota.services import leave as leave_svc

WEEKS_SHOWN = 4


def _blocks(today, open_weekdays, closed, entries_by):
    """Four Monday-based blocks of open days, with a count for each.

    A day is shown if the surgery is open on it, OR the clinician has an
    entry on it — whichever is true. A closed day (or a weekday outside
    open_weekdays) with nothing on it stays hidden: that is not your day
    off, and a weekend is not either. But a closed day, or an
    otherwise-non-open weekday, WITH a published entry is shown anyway:
    hiding a real session from the person rostered to work it is worse
    than the tidiness of omitting an empty row.

    am/pm are looked up straight from entries_by and rendered chip-or-dash
    by the template, not run through cell_state() the way the grid and the
    day view are. That is deliberate, not an oversight: this page is the
    clinician looking at their own schedule, so a ghost leave chip — the
    "approved leave with no entry yet, go check the pattern" integrity
    warning cell_state exists to raise for whoever fixes the rota — has no
    reader here who could act on it. The spec settles this page on
    chip-or-dash only; it does not (yet) settle whether ghosts belong on
    the day view for non-admins, which is why day.py still calls
    cell_state() for that screen.
    """
    monday = today - timedelta(days=today.weekday())
    absence = SessionType.Category.ABSENCE
    blocks = []
    for index in range(WEEKS_SHOWN):
        start = monday + timedelta(weeks=index)
        days = []
        for offset in range(7):
            day = start + timedelta(days=offset)
            am, pm = entries_by.get((day, "AM")), entries_by.get((day, "PM"))
            is_open = day.weekday() in open_weekdays and day not in closed
            if not is_open and am is None and pm is None:
                continue
            day_sessions = [e for e in (am, pm) if e is not None]
            is_leave = bool(day_sessions) and all(
                e.session_type.category == absence for e in day_sessions)
            days.append({"day": day, "am": am, "pm": pm, "is_leave": is_leave})
        sessions = [e for row in days
                    for e in (row["am"], row["pm"]) if e is not None]
        if not days:
            # Nothing to count — "Surgery closed all week" is the body's
            # own words for this; a "0 sessions" label beside it would
            # read as an ordinary week where nothing happened to be
            # booked, which is not what happened.
            label = ""
        elif sessions and all(e.session_type.category == absence
                              for e in sessions):
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

    # Same rule as _blocks(): a session the clinician actually has beats
    # the closure. Checked first and unconditionally, so an entry on a
    # closed or non-open "today" still reports "working" and renders,
    # rather than telling a GP the surgery is shut on a day they have a
    # session sitting in the rota. "closed" and "not_in" are reserved for
    # the no-entry cases below.
    today_am = entries_by.get((today, "AM"))
    today_pm = entries_by.get((today, "PM"))
    if today_am or today_pm:
        today_state = "working"
    elif today in closed or today.weekday() not in open_weekdays:
        today_state = "closed"
    else:
        today_state = "not_in"

    return render(request, "rota/my_schedule.html", {
        "clinician": clinician,
        "today": today,
        "today_state": today_state,
        "today_cells": [today_am, today_pm],
        "today_closed_reason": next(
            (cd.reason for cd in ClosedDay.objects.filter(day=today)), ""),
        "weeks": _blocks(today, open_weekdays, closed, entries_by),
        "leave": leave_svc.leave_summary(clinician, today),
        "my_requests": list(LeaveRequest.objects.filter(
            clinician=clinician, status=LeaveRequest.Status.PENDING
        ).select_related("session_type")),
        "my_swaps": list(SwapRequest.objects.filter(
            proposer=clinician
        ).exclude(status=SwapRequest.Status.DECLINED
                  ).select_related("colleague")[:10]),
        "to_accept": SwapRequest.objects.filter(
            colleague=clinician, status=SwapRequest.Status.PROPOSED
        ).select_related("proposer"),
    })
