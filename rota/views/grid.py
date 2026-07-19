from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rota.models import (ClinicianGroup, ClosedDay, DayNote, LocumRequirement,
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

    entries = RotaEntry.objects.filter(day__in=days).select_related(
        "session_type", "clinician"
    )
    if not is_admin:
        entries = entries.filter(is_published=True)
    cell_map = {(e.clinician_id, e.day, e.part): e for e in entries}

    closed = set(ClosedDay.objects.filter(day__in=days).values_list("day", flat=True))
    notes = {n.day: n for n in DayNote.objects.filter(day__in=days)}
    day_headers = [
        {"day": d, "closed": d in closed, "note": notes.get(d),
         "warnings": day_warnings(d, include_drafts=is_admin)}
        for d in days
    ]

    sections = []
    for group in ClinicianGroup.objects.prefetch_related("clinicians"):
        rows = []
        for clinician in group.clinicians.filter(active=True):
            cells = []
            for d in days:
                am = cell_map.get((clinician.id, d, "AM"))
                pm = cell_map.get((clinician.id, d, "PM"))
                merged = bool(am and pm and am.allocation_group
                              and am.allocation_group == pm.allocation_group)
                for part, entry in (("AM", am), ("PM", pm)):
                    if merged and part == "PM":
                        continue
                    cells.append({
                        "day": d, "day_str": d.isoformat(), "part": part,
                        "entry": entry, "merged": merged and part == "AM",
                        "unavail": not availability.works_on(clinician, d, part),
                        "closed": d in closed,
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
        "colspan": len(days) * 2 + 1,
        "week_end": days[-1] if days else monday,
    })
