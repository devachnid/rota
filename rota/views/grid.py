from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.shortcuts import render

from rota.models import (Clinician, ClinicianGroup, ClosedDay, DayNote,
                         LeaveRequest, LocumRequirement, PatternSlot,
                         PracticeSettings, RotaEntry)
from rota.services import availability
from rota.services.warnings import day_warnings


@login_required
def grid(request):
    try:
        anchor = date.fromisoformat(request.GET.get("week", ""))
    except ValueError:
        anchor = date.today()
    monday = anchor - timedelta(days=anchor.weekday())
    settings = PracticeSettings.load()
    days = [monday + timedelta(days=i) for i in settings.open_weekday_list()]
    is_admin = request.user.is_rota_admin
    has_clinician = getattr(request.user, "clinician", None) is not None

    entries = RotaEntry.objects.filter(day__in=days).select_related(
        "session_type", "clinician", "site"
    )
    if not is_admin:
        entries = entries.filter(is_published=True)
    entries = list(entries)
    cell_map = {(e.clinician_id, e.day, e.part): e for e in entries}

    companion_partner = {}
    by_companion_group = {}
    for e in entries:
        if e.companion_group:
            by_companion_group.setdefault(e.companion_group, []).append(e)
    for group_entries in by_companion_group.values():
        if len(group_entries) != 2:
            continue
        e1, e2 = group_entries
        companion_partner[(e1.clinician_id, e1.day, e1.part)] = e2.clinician.name
        companion_partner[(e2.clinician_id, e2.day, e2.part)] = e1.clinician.name

    active = list(Clinician.objects.filter(active=True))
    pattern_rows = list(PatternSlot.objects.filter(
        clinician__in=active
    ).order_by("effective_from"))
    # min()/max(), not days[0]/days[-1]: parse_int_list preserves input
    # order, so open_weekdays = "4,0,1,2,3" makes the positional pair run
    # backwards and the overlap filter match nothing at all. And `days` can
    # be empty -- open_weekdays = "" parses to [] and PracticeSettings.clean()
    # accepts it -- which is an IndexError on either subscript.
    approved_leave = LeaveRequest.objects.none()
    if days:
        approved_leave = LeaveRequest.objects.filter(
            status=LeaveRequest.Status.APPROVED,
            start_date__lte=max(days), end_date__gte=min(days),
        ).select_related("session_type")
    resolver = availability.AvailabilityResolver(
        pattern_rows, active, approved_leave)

    closed = set(ClosedDay.objects.filter(day__in=days).values_list("day", flat=True))
    notes = {n.day: n for n in DayNote.objects.filter(day__in=days)}
    day_headers = [
        {"day": d, "closed": d in closed, "note": notes.get(d),
         "warnings": day_warnings(d, include_drafts=is_admin) if is_admin else []}
        for d in days
    ]

    sections = []
    groups = ClinicianGroup.objects.prefetch_related(
        Prefetch("clinicians", queryset=Clinician.objects.filter(active=True))
    )
    for group in groups:
        rows = []
        for clinician in group.clinicians.all():
            cells = []
            for d in days:
                am = cell_map.get((clinician.id, d, "AM"))
                pm = cell_map.get((clinician.id, d, "PM"))
                merged = bool(am and pm and am.allocation_group
                              and am.allocation_group == pm.allocation_group)
                for part, entry in (("AM", am), ("PM", pm)):
                    if merged and part == "PM":
                        continue
                    works = resolver.works_on(clinician.id, d, part)
                    leave_type = (resolver.leave_type(clinician.id, d)
                                  if entry is None else None)
                    # Ghost only where it means something: on a session the
                    # clinician works (approval should have written an entry
                    # and did not), or for a clinician with no pattern at all
                    # (nothing would ever show for them otherwise). Ghosting
                    # every session leave spans would put chips on every
                    # part-timer's days off.
                    #
                    # Two things the "no pattern" clause must not skip:
                    #  - the contractual window. leave.sessions_affected()
                    #    and works_on() both refuse to write outside it, so a
                    #    chip there accuses approval of missing an entry it
                    #    was right not to write. `works` already carries the
                    #    window; the no-pattern branch has to ask separately.
                    #  - a closed day. sessions_affected() skips days where
                    #    calendar.is_open() is false, so a bank holiday
                    #    inside a leave range correctly has no entry, and a
                    #    ghost there is noise on every Christmas closure.
                    no_pattern_here = (not resolver.has_pattern(clinician.id)
                                       and resolver.in_service(clinician.id, d))
                    ghostable = ((works or no_pattern_here)
                                 and d not in closed)
                    cells.append({
                        "day": d, "day_str": d.isoformat(), "part": part,
                        "entry": entry, "merged": merged and part == "AM",
                        "off": entry is None and not works,
                        "ghost_leave": leave_type if ghostable else None,
                        "closed": d in closed,
                        "partner": companion_partner.get((clinician.id, d, part)),
                    })
            rows.append({
                "clinician": clinician,
                "mine": clinician.user_id == request.user.id,
                "cells": cells,
            })
        if rows or group.is_locum_group:
            sections.append({"group": group, "rows": rows})

    reqs = LocumRequirement.objects.filter(day__in=days).select_related("session_type")
    req_map = {}
    for r in reqs:
        req_map.setdefault((r.day, r.part), []).append(r)
    locum_cells = [
        {"day": d, "day_str": d.isoformat(), "part": part,
         "reqs": req_map.get((d, part), [])}
        for d in days for part in ["AM", "PM"]
    ]

    return render(request, "rota/grid.html", {
        "monday": monday,
        "prev_week": monday - timedelta(days=7),
        "next_week": monday + timedelta(days=7),
        "days": days,
        "day_headers": day_headers,
        "sections": sections,
        "locum_cells": locum_cells,
        "is_admin": is_admin,
        "has_clinician": has_clinician,
        "colspan": len(days) * 2 + 1,
        # max(), for the same reason as the leave filter above: this is one
        # end of a date range (the Publish button posts monday..week_end into
        # a day__range), and a reordered open_weekdays would make days[-1]
        # earlier than monday and publish nothing.
        "week_end": max(days) if days else monday,
    })
