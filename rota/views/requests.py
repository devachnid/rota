from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from rota.models import RotaEntry, SwapRequest
from rota.services import swaps as swaps_svc
from rota.views.decorators import admin_required, parse_errors_as_400


@admin_required
def inbox(request):
    pending_swaps = [
        {"req": r, "problems": swaps_svc.validate(r)}
        for r in SwapRequest.objects.filter(
            status=SwapRequest.Status.ACCEPTED
        ).select_related("proposer", "colleague")
    ]
    return render(request, "rota/inbox.html", {
        "pending_swaps": pending_swaps,
    })


@login_required
@parse_errors_as_400
def swap_new(request):
    clinician = getattr(request.user, "clinician", None)
    if clinician is None:
        return HttpResponseForbidden("No clinician profile linked to this account.")
    today = date.today()
    mine = RotaEntry.objects.filter(
        clinician=clinician, is_published=True, day__gte=today
    ).select_related("session_type")
    theirs = RotaEntry.objects.filter(
        is_published=True, day__gte=today, clinician__user__isnull=False,
    ).exclude(clinician=clinician).select_related("session_type", "clinician")
    if request.method == "POST":
        my_entry = get_object_or_404(mine, pk=request.POST["my_entry_id"])
        their_entry = get_object_or_404(theirs, pk=request.POST["their_entry_id"])
        SwapRequest.objects.create(
            proposer=clinician, proposer_day=my_entry.day,
            proposer_part=my_entry.part,
            colleague=their_entry.clinician, colleague_day=their_entry.day,
            colleague_part=their_entry.part,
            message=request.POST.get("message", ""),
        )
        messages.success(request, "Swap proposed — awaiting your colleague.")
        return redirect("/me/")
    return render(request, "rota/swap_form.html", {"mine": mine,
                                                   "theirs": theirs})


@login_required
@require_POST
def swap_accept(request, pk):
    req = get_object_or_404(SwapRequest, pk=pk)
    try:
        swaps_svc.accept(req, request.user)
        messages.success(request, "Swap accepted — awaiting admin approval.")
    except (PermissionError, ValueError) as e:
        messages.error(request, str(e))
    return redirect("/me/")


@login_required
@require_POST
def swap_colleague_decline(request, pk):
    req = get_object_or_404(SwapRequest, pk=pk)
    try:
        swaps_svc.decline_by_colleague(req, request.user)
        messages.success(request, "Swap declined.")
    except (PermissionError, ValueError) as e:
        messages.error(request, str(e))
    return redirect("/me/")


@admin_required
@require_POST
def swap_approve(request, pk):
    req = get_object_or_404(SwapRequest, pk=pk,
                            status=SwapRequest.Status.ACCEPTED)
    try:
        swaps_svc.approve(request.user, req)
        messages.success(request, "Swap applied.")
    except ValueError as e:
        messages.error(request, str(e))
    return redirect("/requests/")


@admin_required
@require_POST
def swap_decline(request, pk):
    req = get_object_or_404(
        SwapRequest, pk=pk,
        status__in=[SwapRequest.Status.PROPOSED, SwapRequest.Status.ACCEPTED],
    )
    try:
        swaps_svc.decline(request.user, req, request.POST.get("comment", ""))
        messages.success(request, "Swap declined.")
    except ValueError as e:
        messages.error(request, str(e))
    return redirect("/requests/")
