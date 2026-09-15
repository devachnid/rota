from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rota.services import grid as grid_svc
from rota.services.breathe.links import (unlinked_changelist_url,
                                         unlinked_clinicians)


@login_required
def grid(request):
    is_admin = request.user.is_rota_admin
    tick = is_admin and request.GET.get("tick") == "1"
    anchor = grid_svc.parse_anchor(request.GET.get("week"))
    window = grid_svc.Window(anchor, is_admin, request.user)
    step = timedelta(days=7 * grid_svc.STEP_WEEKS)
    return render(request, "rota/grid.html", {
        "anchor": anchor,
        "start": window.start,
        "end": window.end,
        "earlier": anchor - step,
        "later": anchor + step,
        "today": window.today,
        "today_shown": window.today in window.days,
        "weeks": window.weeks(),
        "day_headers": window.day_headers(),
        "sections": window.sections(),
        "locum_cells": window.locum_cells(),
        "cols": len(window.days) * 2,
        "colspan": len(window.days) * 2 + 1,
        "is_admin": is_admin,
        "tick": tick,
        "has_clinician": getattr(request.user, "clinician", None) is not None,
        "unlinked_count": unlinked_clinicians().count() if is_admin else 0,
        "unlinked_url": unlinked_changelist_url(),
    })
