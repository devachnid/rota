from django.db import transaction
from django.utils import timezone

from rota.models import (BreatheAbsence, BreatheLeaveMapping, PatternSlot,
                         RotaEntry, RotaEntryLog, SwapRequest)
from rota.services import availability


def _log(actor, day, part, name, action, detail=""):
    RotaEntryLog.objects.create(day=day, part=part, clinician_name=name,
                                actor=actor, action=action, detail=detail)


def _expand(clinician, day, part):
    entry = RotaEntry.objects.filter(clinician=clinician, day=day,
                                     part=part).first()
    if entry and entry.allocation_group:
        return [(day, "AM"), (day, "PM")]
    return [(day, part)]


def involved_slots(req):
    slots = _expand(req.proposer, req.proposer_day, req.proposer_part)
    for s in _expand(req.colleague, req.colleague_day, req.colleague_part):
        if s not in slots:
            slots.append(s)
    return slots


def validate(req):
    # Single pass over involved_slots: each (clinician, slot) entry is
    # fetched once and checked for both conditions. The two problem kinds
    # are collected into separate lists and concatenated at the end so the
    # existing ordering (all "no session" problems before any "paired
    # session" problems) is preserved exactly.
    no_session = []
    paired = []
    slots = list(involved_slots(req))
    for day, part in slots:
        for clinician in (req.proposer, req.colleague):
            entry = RotaEntry.objects.filter(clinician=clinician, day=day,
                                             part=part).first()
            if entry is None:
                no_session.append(
                    f"{clinician.name} has no session on {day} {part} — "
                    "both GPs must work every session involved.")
            elif entry.companion_group:
                paired.append(
                    f"{clinician.name}'s {day} {part} is a paired session "
                    "(mentoring) and cannot be swapped.")

    # A swap gives each clinician the other's session. Neither may be on
    # Breathe leave for the session they would receive — this is the only
    # gate now that leave is not approved here. Built once per validation:
    # two clinicians, two slots.
    people = [req.proposer, req.colleague]
    days = [d for d, _ in slots]
    resolver = availability.AvailabilityResolver(
        PatternSlot.objects.filter(clinician__in=people),
        people,
        BreatheAbsence.objects.filter(clinician__in=people,
                                      start_date__lte=max(days), end_date__gte=min(days)),
        BreatheLeaveMapping.as_dict(),
    )
    on_leave = []
    receives = {req.proposer: (req.colleague_day, req.colleague_part),
                req.colleague: (req.proposer_day, req.proposer_part)}
    for clinician, (day, part) in receives.items():
        if resolver.on_leave(clinician.id, day, part):
            on_leave.append(
                f"{clinician.name} is on leave on {day} {part} (from Breathe) "
                "and cannot take that session.")
    return no_session + paired + on_leave


def accept(req, user):
    if req.colleague.user_id != user.id:
        raise PermissionError("Only the named colleague can accept this swap.")
    if req.status != SwapRequest.Status.PROPOSED:
        raise ValueError("Swap is not awaiting colleague acceptance.")
    req.status = SwapRequest.Status.ACCEPTED
    req.save()


def decline_by_colleague(req, user):
    if req.colleague.user_id != user.id:
        raise PermissionError("Only the named colleague can decline this swap.")
    if req.status != SwapRequest.Status.PROPOSED:
        raise ValueError("Swap is no longer awaiting your response.")
    req.status = SwapRequest.Status.DECLINED
    req.save()


@transaction.atomic
def approve(actor, req):
    if req.status != SwapRequest.Status.ACCEPTED:
        raise ValueError("Swap must be accepted by the colleague first.")
    problems = validate(req)
    if problems:
        raise ValueError("; ".join(problems))
    for day, part in involved_slots(req):
        e1 = RotaEntry.objects.get(clinician=req.proposer, day=day, part=part)
        e2 = RotaEntry.objects.get(clinician=req.colleague, day=day, part=part)
        for attr in ("session_type", "site", "note", "allocation_group"):
            v1, v2 = getattr(e1, attr), getattr(e2, attr)
            setattr(e1, attr, v2)
            setattr(e2, attr, v1)
        e1.manually_set = e2.manually_set = True
        e1.save()
        e2.save()
        _log(actor, day, part, req.proposer.name, "swapped",
             f"with {req.colleague.name}")
    req.status = SwapRequest.Status.APPROVED
    req.decided_by = actor
    req.decided_at = timezone.now()
    req.save()


def decline(actor, req, comment=""):
    if req.status not in (SwapRequest.Status.PROPOSED, SwapRequest.Status.ACCEPTED):
        raise ValueError("Swap has already been decided.")
    req.status = SwapRequest.Status.DECLINED
    req.admin_comment = comment
    req.decided_by = actor
    req.decided_at = timezone.now()
    req.save()
