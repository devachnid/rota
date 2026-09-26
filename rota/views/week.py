"""The week on a phone (review 7B).

The week grid is forty columns, which is a desktop screen; the phone's Week
tab opens this instead. One week at a time, a card per open day: the date,
how many are in and on leave, and the pinned roles (the types ticked "Pin
on day view" — Duty, typically), all visible while the card is closed;
open it for everyone's sessions. Today's card starts open.

Read-only for everyone, and no staffing warnings, admin or not: this is
for looking someone up, and editing stays on the grid. Each day's lists
come from rota/services/roster.py, the same place the day view gets its
own, so the two cannot disagree about a day.
"""

from datetime import timedelta
from itertools import groupby

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rota.models import PracticeSettings, SessionType
from rota.services import grid as grid_svc
from rota.services.roster import RosterSource


def _pins(pinned):
    """The pinned rows as one line per role: Duty — Blake Rowe AM ·
    Indigo Ames PM. They arrive sorted by type name, then person."""
    return [{"type": t, "people": list(rows)}
            for t, rows in groupby(pinned, key=lambda r: r["entry"].session_type)]


def _leave_name(row):
    """What someone's leave is, for "Drew Tanner (Holiday)": what Breathe
    calls it, or an absence entry's type. Not the first chip on the row —
    someone on leave may still be rostered on something (a clash), and
    "Drew Tanner (Duty)" under On leave says the opposite of the truth."""
    absence = SessionType.Category.ABSENCE
    for cell in row["cells"]:
        if cell["on_leave"] and cell["leave_label"]:
            return cell["leave_label"]
        if cell["entry"] and cell["entry"].session_type.category == absence:
            return cell["entry"].session_type.name
    return None


@login_required
def week_view(request):
    monday = grid_svc.parse_anchor(request.GET.get("week"))
    settings = PracticeSettings.load()
    days = sorted(monday + timedelta(days=o) for o in settings.open_weekday_list())
    source = RosterSource(days, include_drafts=request.user.is_rota_admin)
    today = grid_svc._today()
    cards = []
    for d in days:
        shown = source.day(d)
        cards.append({
            "day": shown,
            "anchor": f"d-{d.isoformat()}",
            "today": d == today,
            "pins": _pins(shown.pinned),
            "leave": [(r["clinician"], _leave_name(r)) for r in shown.on_leave],
        })
    return render(request, "rota/week.html", {
        "monday": monday,
        "cards": cards,
        "prev_week": monday - timedelta(days=7),
        "next_week": monday + timedelta(days=7),
        "this_week": grid_svc.week_monday(today),
    })
