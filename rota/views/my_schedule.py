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
            days.append({"day": day, "am": am, "pm": pm})
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

    if today in closed or today.weekday() not in open_weekdays:
        today_state = "closed"
    elif entries_by.get((today, "AM")) or entries_by.get((today, "PM")):
        today_state = "working"
    else:
        today_state = "not_in"

    return render(request, "rota/my_schedule.html", {
        "clinician": clinician,
        "today": today,
        "today_state": today_state,
        "today_cells": [entries_by.get((today, "AM")),
                        entries_by.get((today, "PM"))],
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
