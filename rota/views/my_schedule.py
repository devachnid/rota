from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rota.models import LeaveRequest, RotaEntry, SwapRequest
from rota.services import leave as leave_svc


@login_required
def my_schedule(request):
    clinician = getattr(request.user, "clinician", None)
    if clinician is None:
        return render(request, "rota/my_schedule.html", {"clinician": None})
    today = date.today()
    return render(request, "rota/my_schedule.html", {
        "clinician": clinician,
        "entries": RotaEntry.objects.filter(
            clinician=clinician, is_published=True,
            day__range=(today, today + timedelta(days=28)),
        ).select_related("session_type", "site"),
        "leave": leave_svc.leave_summary(clinician, today),
        "my_leave_requests": LeaveRequest.objects.filter(
            clinician=clinician, status=LeaveRequest.Status.PENDING
        ).select_related("session_type"),
        "my_swaps": SwapRequest.objects.filter(
            proposer=clinician
        ).exclude(status=SwapRequest.Status.DECLINED).select_related(
            "colleague")[:10],
        "to_accept": SwapRequest.objects.filter(
            colleague=clinician, status=SwapRequest.Status.PROPOSED
        ).select_related("proposer"),
    })
