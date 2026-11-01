from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rota.services import grid as grid_svc
from rota.services.shift_central.links import without_email, without_email_changelist_url


@login_required
def grid(request):
    is_admin = request.user.is_rota_admin
    tick = is_admin and request.GET.get("tick") == "1"
    anchor = grid_svc.parse_anchor(request.GET.get("week"))
    window = grid_svc.Window(anchor, is_admin, request.user)
    step = timedelta(days=7 * grid_svc.STEP_WEEKS)
    weeks = window.weeks()
    sections = window.sections()
    return render(request, "rota/grid.html", {
        "anchor": anchor,
        "start": window.start,
        "end": window.end,
        "earlier": anchor - step,
        "later": anchor + step,
        "today": window.today,
        "today_shown": window.today in window.days,
        "weeks": weeks,
        # The week row carries only Publish buttons and week ceiling
        # warnings, so it is rendered only when some week has one.
        "show_week_row": is_admin and any(w["drafts"] or w["warnings"] for w in weeks),
        "day_headers": window.day_headers(),
        "sections": sections,
        "locum_cells": window.locum_cells(),
        "cols": len(window.days) * 2,
        "view_cols": window.view_cols,
        # The longest row label on the page, which sizes the name column
        # (components.css). Initials fit its 5.5rem floor; only a locum's
        # "S Jones" widens it, and only while they have a row.
        "name_ch": max((len(row["label"]) for s in sections for row in s["rows"]), default=0),
        "colspan": len(window.days) * 2 + 1,
        "is_admin": is_admin,
        "tick": tick,
        "has_clinician": getattr(request.user, "clinician", None) is not None,
        "without_email_count": without_email().count() if is_admin else 0,
        "without_email_url": without_email_changelist_url(),
    })
