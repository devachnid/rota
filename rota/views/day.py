from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rota.models import (BreatheAbsence, BreatheLeaveMapping, Clinician,
                         ClosedDay, DayNote, PatternSlot, PracticeSettings,
                         RotaEntry, SessionType)
from rota.services import availability
from rota.services.cells import cell_state

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

    is_closed = (target in nearby_closed
                 or target.weekday() not in open_weekdays)

    entries = RotaEntry.objects.filter(day=target).select_related(
        "session_type", "clinician", "site")
    if not request.user.is_rota_admin:
        entries = entries.filter(is_published=True)
    entries = list(entries)

    by_clinician = {}
    for e in entries:
        by_clinician.setdefault(e.clinician_id, {})[e.part] = e

    partner = {}
    groups = {}
    for e in entries:
        if e.companion_group:
            groups.setdefault(e.companion_group, []).append(e)
    for pair in groups.values():
        if len(pair) == 2:
            a, b = pair
            partner[(a.clinician_id, a.part)] = b.clinician.name
            partner[(b.clinician_id, b.part)] = a.clinician.name

    active = list(Clinician.objects.filter(active=True).order_by("name"))
    pattern_rows = list(PatternSlot.objects.filter(clinician__in=active))
    absences = BreatheAbsence.objects.filter(
        clinician__in=active,
        start_date__lte=target, end_date__gte=target,
    )
    resolver = availability.AvailabilityResolver(
        pattern_rows, active, absences, BreatheLeaveMapping.as_dict())

    # Filtered by the same in-service test the roster loop below applies —
    # otherwise a clinician past their end_date with a stray entry for a
    # pinned session type would appear here despite belonging to none of
    # roster / on-leave / not-in.
    pinned = sorted(
        (e for e in entries
         if e.session_type.pin_on_day_view
         and resolver.in_service(e.clinician_id, target)),
        key=lambda e: (e.session_type.name, e.clinician.name, e.part),
    )

    roster, on_leave, not_in = [], [], []
    for c in active:
        if not resolver.in_service(c.id, target):
            continue
        mine = by_clinician.get(c.id, {})
        cells = [
            cell_state(c.id, target, part, entry=mine.get(part),
                       resolver=resolver, closed=is_closed,
                       partner=partner.get((c.id, part)))
            for part in ("AM", "PM")
        ]
        # On-leave means every part the clinician works is covered — either
        # by a Breathe absence for this day/part, or (for history predating
        # the overlay) by an absence-category entry. A cell is "off" when
        # nothing is expected there at all (cell_state already worked that
        # out); a part where off is False is a part they work, and it needs
        # one of those two to count as covered. A clinician with no worked
        # parts at all (nothing to cover) is never "on leave" — that's
        # not_in below.
        #
        # `on_leave`, not `absence`: `absence` is the mapped chip, so with a
        # kind's default mapping row missing, a sick clinician read "1 in ·
        # 0 on leave" — the count and the scheduler disagreeing about the
        # same person. What renders is still `absence`; what is counted is
        # what Breathe said.
        absence = SessionType.Category.ABSENCE
        worked_cells = [cell for cell in cells if not cell["off"]]
        is_on_leave = bool(worked_cells) and all(
            cell["on_leave"]
            or (cell["entry"] and cell["entry"].session_type.category == absence)
            for cell in worked_cells
        )
        if is_on_leave:
            on_leave.append({"clinician": c, "cells": cells})
        elif mine or any(not cell["off"] or cell["absence"]
                          for cell in cells):
            # cell["absence"] alone (off True, no entry) is the "no pattern
            # entered yet" case: cell_state shows it precisely because
            # nothing else would ever show for that clinician. The grid
            # renders that chip too; filing them under "Not in" instead
            # would drop the integrity warning and assert a lie — that they
            # do not work this day — when the truth is nobody has entered
            # their pattern.
            roster.append({"clinician": c, "cells": cells})
        else:
            not_in.append(c)

    # A closure statement is true and worth showing, but it is not a reason
    # to withhold rostered work: when the day carries real RotaEntry rows,
    # the body renders alongside the closure line, not instead of it. This
    # is deliberately keyed on `entries`, not on `roster` being non-empty —
    # a clinician whose pattern says they work a closed Tuesday still lands
    # in `roster` as a dash row even with zero entries that day, and that
    # must not be enough to light up the body on its own. Only a closed day
    # with no entries at all keeps the old behaviour — the closure line
    # alone, and the header count line suppressed along with the body it
    # would otherwise describe.
    has_entries = bool(entries)
    show_body = not is_closed or has_entries

    return render(request, "rota/day.html", {
        "target": target,
        "is_closed": is_closed,
        "show_body": show_body,
        "closed_reason": next(
            (cd.reason for cd in ClosedDay.objects.filter(day=target)), ""),
        "roster": roster,
        "on_leave": on_leave,
        "not_in": not_in,
        "in_count": len(roster),
        "leave_count": len(on_leave),
        "weekday_name": target.strftime("%A"),
        "day_note": DayNote.objects.filter(day=target).first(),
        "is_admin": request.user.is_rota_admin,
        "pinned": pinned,
        "prev_day": prev_day,
        "next_day": next_day,
    })
