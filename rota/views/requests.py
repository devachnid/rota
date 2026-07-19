from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from rota.models import Clinician, LeaveRequest, SessionType
from rota.services import leave as leave_svc
from rota.views.decorators import admin_required, parse_errors_as_400


@login_required
@parse_errors_as_400
def leave_new(request):
    try:
        clinician = request.user.clinician
    except Clinician.DoesNotExist:
        return HttpResponseForbidden("No clinician profile linked to this account.")
    absence_types = SessionType.objects.filter(category="ABSENCE")
    if request.method == "POST":
        LeaveRequest.objects.create(
            clinician=clinician,
            session_type=get_object_or_404(
                absence_types, pk=request.POST["session_type_id"]),
            start_date=date.fromisoformat(request.POST["start_date"]),
            end_date=date.fromisoformat(request.POST["end_date"]),
            message=request.POST.get("message", ""),
        )
        messages.success(request, "Leave request submitted.")
        return redirect("/me/")
    return render(request, "rota/leave_form.html",
                  {"absence_types": absence_types})


@admin_required
def inbox(request):
    pending_leave = [
        {"req": r,
         "overwritten": leave_svc.entries_overwritten(r),
         "n_sessions": len(leave_svc.sessions_affected(r))}
        for r in LeaveRequest.objects.filter(
            status=LeaveRequest.Status.PENDING
        ).select_related("clinician", "session_type")
    ]
    return render(request, "rota/inbox.html", {"pending_leave": pending_leave})


@admin_required
@require_POST
def leave_approve(request, pk):
    req = get_object_or_404(LeaveRequest, pk=pk,
                            status=LeaveRequest.Status.PENDING)
    leave_svc.approve(request.user, req, request.POST.get("comment", ""))
    messages.success(request, f"Approved leave for {req.clinician.name}.")
    return redirect("/requests/")


@admin_required
@require_POST
def leave_decline(request, pk):
    req = get_object_or_404(LeaveRequest, pk=pk,
                            status=LeaveRequest.Status.PENDING)
    leave_svc.decline(request.user, req, request.POST.get("comment", ""))
    messages.success(request, f"Declined leave for {req.clinician.name}.")
    return redirect("/requests/")
