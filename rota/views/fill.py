from datetime import date, timedelta

from django.shortcuts import render

from rota.services.fill import run_fill
from rota.views.decorators import admin_required, parse_errors_as_400


@admin_required
@parse_errors_as_400
def fill(request):
    today = date.today()
    next_monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    context = {
        "start": next_monday,
        "end": next_monday + timedelta(days=27),
        "result": None,
    }
    if request.method == "POST":
        start = date.fromisoformat(request.POST["start"])
        end = date.fromisoformat(request.POST["end"])
        context.update({
            "start": start, "end": end,
            "result": run_fill(request.user, start, end,
                               fill_default=bool(request.POST.get("fill_default"))),
        })
    return render(request, "rota/fill.html", context)
