"""The read-only feed Shift Central polls (its spec, section 9).

GET /api/v1/sessions?from=YYYY-MM-DD&to=YYYY-MM-DD
    {"from": "…", "to": "…",
     "sessions": [{"email": "a.gp@…", "day": "2027-01-04", "part": "AM",
                   "type": "Surgery", "site": "AG", "note": ""}],
     "without_email": 1}
    Published entries whose clinician has a login with an email, from and
    to inclusive, at most 500 days. `without_email` counts the clinicians
    with published entries in the range but no email, so the other side can
    say someone is missing. Nothing here is written to.
"""

from datetime import date

from django.http import JsonResponse

from api.auth import token_required
from rota.models import RotaEntry

MAX_DAYS = 500


def _bad(message):
    return JsonResponse({"error": message}, status=400)


@token_required
def sessions(request):
    try:
        start = date.fromisoformat(request.GET.get("from", ""))
        end = date.fromisoformat(request.GET.get("to", ""))
    except ValueError:
        return _bad("from and to must be dates (YYYY-MM-DD)")
    if end < start:
        return _bad("to is before from")
    if (end - start).days > MAX_DAYS:
        return _bad(f"the range is over {MAX_DAYS} days")
    rows = (RotaEntry.objects.filter(is_published=True, day__range=(start, end))
            .select_related("clinician__user", "session_type", "site").order_by("day", "part", "clinician__name"))
    out, without_email = [], set()
    for e in rows:
        user = e.clinician.user
        if user is None or not user.email:
            without_email.add(e.clinician_id)
            continue
        out.append({"email": user.email, "day": e.day.isoformat(), "part": e.part, "type": e.session_type.name,
                    "site": e.site.name if e.site else "", "note": e.note})
    return JsonResponse({"from": start.isoformat(), "to": end.isoformat(), "sessions": out,
                         "without_email": len(without_email)})
