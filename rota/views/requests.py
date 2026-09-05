from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from rota.forms import SwapForm
from rota.models import Clinician, RotaEntry, SwapRequest
from rota.services import swaps as swaps_svc
from rota.views.decorators import admin_required


@admin_required
def inbox(request):
    pending_swaps = [
        {"req": r, "problems": swaps_svc.validate(r), "what": swaps_svc.describe(r)}
        for r in SwapRequest.objects.filter(
            status=SwapRequest.Status.ACCEPTED
        ).select_related("proposer", "colleague")
    ]
    return render(request, "rota/inbox.html", {
        "pending_swaps": pending_swaps,
    })


def _nothing_to_swap(clinician, mine, theirs):
    """Why the propose-a-swap page has nothing to offer, or "" when it has.

    The colleague list is the half that surprises people: it holds only
    colleagues with a login account, because the colleague accepts the swap
    themselves, so a practice where nobody else has an account yet sees an
    empty list. Name which condition is unmet rather than showing an empty
    dropdown."""
    if not mine.exists():
        return ("You have no published sessions coming up, so there is "
                "nothing to swap yet.")
    if theirs.exists():
        return ""
    others_can_sign_in = Clinician.objects.filter(
        user__isnull=False).exclude(pk=clinician.pk).exists()
    if not others_can_sign_in:
        return ("None of your colleagues has a login account yet, and a swap "
                "can only be proposed to someone who can sign in to accept "
                "it. Ask the rota admin.")
    return ("None of your colleagues who can sign in has a published session "
            "coming up, so there is nothing to swap with yet.")


@login_required
def swap_new(request):
    clinician = getattr(request.user, "clinician", None)
    if clinician is None:
        return HttpResponseForbidden("No clinician profile linked to this account.")
    today = date.today()
    mine = RotaEntry.objects.filter(
        clinician=clinician, is_published=True, day__gte=today
    ).select_related("session_type")
    # Only a colleague who can sign in can accept a swap, so only their
    # sessions are offered. Ordered by colleague so the page can group them:
    # a swap is agreed with a person first and a date second.
    theirs = RotaEntry.objects.filter(
        is_published=True, day__gte=today, clinician__user__isnull=False,
    ).exclude(clinician=clinician).select_related(
        "session_type", "clinician").order_by("clinician__name", "day", "part")
    form = SwapForm(mine, theirs,
                    request.POST if request.method == "POST" else None)
    if form.is_valid():
        my_entry = form.cleaned_data["my_entry_id"]
        their_entry = form.cleaned_data["their_entry_id"]
        req = SwapRequest(
            proposer=clinician, proposer_day=my_entry.day,
            proposer_part=my_entry.part,
            colleague=their_entry.clinician, colleague_day=their_entry.day,
            colleague_part=their_entry.part,
            message=form.cleaned_data["message"],
        )
        # Checked now as well as at approval, so a colleague is never asked
        # about a swap that could not be applied as the rota stands.
        problems = swaps_svc.validate(req)
        if not problems:
            req.save()
            messages.success(request, "Swap proposed — awaiting your colleague.")
            return redirect("/me/")
        for problem in problems:
            form.add_error(None, problem)
    return render(request, "rota/swap_form.html", {
        "form": form, "mine": mine, "theirs": theirs,
        "nothing_to_swap": _nothing_to_swap(clinician, mine, theirs),
    })


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
