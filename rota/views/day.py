from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rota.models import ClosedDay, PracticeSettings
from rota.services.roster import RosterSource

_STEP_LIMIT = 14  # a fortnight: enough to clear Christmas, short enough to end


def _adjacent_open_day(target, delta, open_weekdays, closed):
    """The previous or next day the surgery is open.

    Bounded, because open_weekdays can legitimately be empty — it parses from
    a free-text field that clean() accepts blank — and an unbounded walk
    looking for an open day would then never return.
    """
    if not open_weekdays:
        return target + timedelta(days=delta)
    day = target
    for _ in range(_STEP_LIMIT):
        day += timedelta(days=delta)
        if day.weekday() in open_weekdays and day not in closed:
            return day
    return target + timedelta(days=delta)


@login_required
def day_view(request, day=None):
    try:
        target = date.fromisoformat(day) if day else date.today()
    except (TypeError, ValueError):
        # Matches how grid() treats a malformed ?week=: fall back rather than
        # raise, so the two screens behave alike on a mistyped URL.
        target = date.today()

    settings = PracticeSettings.load()

    span = timedelta(days=_STEP_LIMIT)
    nearby_closed = set(ClosedDay.objects.filter(
        day__range=(target - span, target + span)
    ).values_list("day", flat=True))
    open_weekdays = set(settings.open_weekday_list())
    prev_day = _adjacent_open_day(target, -1, open_weekdays, nearby_closed)
    next_day = _adjacent_open_day(target, +1, open_weekdays, nearby_closed)

    shown = RosterSource([target], include_drafts=request.user.is_rota_admin).day(target)

    return render(request, "rota/day.html", {
        "target": target,
        "is_closed": shown.is_closed,
        "show_body": shown.show_body,
        "closed_reason": shown.closed_reason,
        "roster": shown.roster,
        "on_leave": shown.on_leave,
        "not_in": shown.not_in,
        "in_count": shown.in_count,
        "leave_count": shown.leave_count,
        "weekday_name": target.strftime("%A"),
        "day_note": shown.note,
        "is_admin": request.user.is_rota_admin,
        "pinned": shown.pinned,
        "prev_day": prev_day,
        "next_day": next_day,
    })
