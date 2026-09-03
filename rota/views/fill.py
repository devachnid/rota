from datetime import date, timedelta

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from rota.models import PracticeSettings
from rota.services import entries as entries_svc
from rota.services.fill import run_fill
from rota.views.decorators import admin_required, parse_errors_as_400


def _fmt_day(d):
    return f"{d.day} {d.strftime('%b')}"


def _group_unfilled(unfilled):
    """Group FillResult.unfilled for display by (session_type, reason), with
    a count and a compact date range, so a realistic multi-week fill (which
    can produce ~100+ individual rows) stays readable on the fill screen.
    This is purely a display concern — FillResult.unfilled itself is left
    untouched for callers/tests that rely on its per-slot structure."""
    groups = {}
    order = []
    for u in unfilled:
        key = (u.session_type, u.reason)
        if key not in groups:
            groups[key] = {"session_type": u.session_type, "reason": u.reason,
                           "days": [], "parts": set()}
            order.append(key)
        groups[key]["days"].append(u.day)
        groups[key]["parts"].add(u.part)
    rows = []
    for key in order:
        g = groups[key]
        days = sorted(g["days"])
        start, end = days[0], days[-1]
        date_range = (_fmt_day(start) if start == end
                     else f"{_fmt_day(start)} – {_fmt_day(end)}")
        # Preserve the old per-row "(full day)" rendering for a None part;
        # only show a part label at all when every occurrence agrees on one.
        parts = g["parts"]
        part_label = ((parts.pop() or "(full day)") if len(parts) == 1 else "")
        rows.append({
            "session_type": g["session_type"], "reason": g["reason"],
            "count": len(g["days"]), "date_range": date_range,
            "part_label": part_label,
        })
    return rows


def _base_context():
    today = date.today()
    next_monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    return {
        "start": next_monday,
        "end": next_monday + timedelta(days=27),
        "result": None,
        "default_type": PracticeSettings.load().default_fill_session_type,
    }


@admin_required
@parse_errors_as_400
def fill(request):
    context = _base_context()
    if request.method == "POST":
        start = date.fromisoformat(request.POST["start"])
        end = date.fromisoformat(request.POST["end"])
        result = run_fill(request.user, start, end,
                          fill_default=bool(request.POST.get("fill_default")))
        context.update({
            "start": start, "end": end,
            "result": result,
            "unfilled_groups": _group_unfilled(result.unfilled),
        })
    return render(request, "rota/fill.html", context)


def _delete_scope(post):
    """(start, end, include_manual) from the card's fields. A range whose
    end precedes its start is refused rather than silently matching
    nothing: the preview would say "0 drafts" about a typo."""
    include_manual = post.get("scope", "all") != "fill"
    if post.get("range", "all") == "dates":
        start = date.fromisoformat(post["start"])
        end = date.fromisoformat(post["end"])
        if end < start:
            raise ValueError("The end date is before the start date.")
    else:
        start = end = None
    return start, end, include_manual


@admin_required
@parse_errors_as_400
@require_POST
def delete_drafts(request):
    """Two POSTs. The first renders a preview — how many, how many placed by
    hand, which dates — and deletes nothing. The second, carrying `confirm`,
    deletes. The fill re-run's no-confirmation exemption does not apply: this
    button can remove work an admin placed by hand."""
    start, end, include_manual = _delete_scope(request.POST)
    if not request.POST.get("confirm"):
        qs = entries_svc.drafts(start, end, include_manual=include_manual)
        context = _base_context()
        context["delete_preview"] = {
            "count": qs.count(),
            "hand_placed": qs.filter(manually_set=True).count(),
            "start": start, "end": end,
            "scope": request.POST.get("scope", "all"),
            "range": request.POST.get("range", "all"),
            "include_manual": include_manual,
        }
        return render(request, "rota/fill.html", context)
    deleted, _ = entries_svc.delete_drafts(
        request.user, start, end, include_manual=include_manual)
    messages.success(request, f"Deleted {deleted} draft{'' if deleted == 1 else 's'}.")
    return redirect("/rota/fill/")
