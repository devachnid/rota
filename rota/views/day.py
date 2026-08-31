from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rota.models import (Clinician, ClosedDay, DayNote, LeaveRequest,
                         PatternSlot, PracticeSettings, RotaEntry, SessionType)
from rota.services import availability
from rota.services.cells import cell_state


@login_required
def day_view(request, day=None):
    try:
        target = date.fromisoformat(day) if day else date.today()
    except (TypeError, ValueError):
        # Matches how grid() treats a malformed ?week=: fall back rather than
        # raise, so the two screens behave alike on a mistyped URL.
        target = date.today()

    settings = PracticeSettings.load()
    closed_days = set(
        ClosedDay.objects.filter(day=target).values_list("day", flat=True))
    is_closed = (target in closed_days
                 or target.weekday() not in settings.open_weekday_list())

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
    approved_leave = LeaveRequest.objects.filter(
        status=LeaveRequest.Status.APPROVED,
        start_date__lte=target, end_date__gte=target,
    ).select_related("session_type")
    resolver = availability.AvailabilityResolver(
        pattern_rows, active, approved_leave)

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
        absence = SessionType.Category.ABSENCE
        if mine and all(e.session_type.category == absence for e in mine.values()):
            on_leave.append({"clinician": c, "cells": cells})
        elif mine or any(not cell["off"] for cell in cells):
            roster.append({"clinician": c, "cells": cells})
        else:
            not_in.append(c)

    return render(request, "rota/day.html", {
        "target": target,
        "is_closed": is_closed,
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
    })
