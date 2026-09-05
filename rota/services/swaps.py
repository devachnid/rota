"""Swaps: a GP proposes exchanging one of their sessions with a colleague's,
the colleague accepts, an admin applies it.

Two kinds, told apart from the rota itself when the swap is checked:

WORK   — both GPs already work both sessions. What each does in them is
         exchanged (session type, site, note, full-day grouping); the people
         stay where they are. The duty-swap case.
PEOPLE — each GP works only their own session. The sessions change hands:
         the proposer's entry becomes the colleague's and vice versa, each
         keeping what it is. The cover-for-each-other case.

Anything in between is refused with a sentence naming the facts that break
both patterns. A full duty day (allocation_group) counts as a whole on
either side.
"""

from django.db import transaction
from django.utils import timezone

from rota.models import (BreatheAbsence, BreatheLeaveMapping, PatternSlot,
                         RotaEntry, RotaEntryLog, SwapRequest)
from rota.services import availability

WORK = "work"
PEOPLE = "people"


def when(day, part):
    """'Fri 11 Sep PM' — how every swap message names a session."""
    return f"{day:%a %-d %b} {part}"


def _join(slots):
    """'Fri 11 Sep AM/PM and Mon 14 Sep AM'."""
    by_day = {}
    for day, part in slots:
        by_day.setdefault(day, []).append(part)
    return " and ".join(f"{day:%a %-d %b} {'/'.join(parts)}"
                        for day, parts in by_day.items())


def _log(actor, day, part, name, action, detail=""):
    RotaEntryLog.objects.create(day=day, part=part, clinician_name=name,
                                actor=actor, action=action, detail=detail)


def _expand(clinician, day, part):
    entry = RotaEntry.objects.filter(clinician=clinician, day=day,
                                     part=part).first()
    if entry and entry.allocation_group:
        return [(day, "AM"), (day, "PM")]
    return [(day, part)]


def sides(req):
    """(proposer's slots, colleague's slots), each expanded to the whole day
    when the session put forward is half of a full duty day."""
    return (_expand(req.proposer, req.proposer_day, req.proposer_part),
            _expand(req.colleague, req.colleague_day, req.colleague_part))


def involved_slots(req):
    mine, theirs = sides(req)
    return mine + [s for s in theirs if s not in mine]


def _entries(req):
    """{(clinician_id, day, part): RotaEntry} for both GPs over every slot
    involved — one query, so the checks below cost nothing per slot."""
    slots = set(involved_slots(req))
    rows = RotaEntry.objects.filter(
        clinician__in=[req.proposer, req.colleague],
        day__in={day for day, _ in slots})
    return {(e.clinician_id, e.day, e.part): e
            for e in rows if (e.day, e.part) in slots}


def kind(req, have=None):
    """WORK, PEOPLE, or None when the rota fits neither pattern (or a GP no
    longer has the session they put forward)."""
    mine, theirs = sides(req)
    have = _entries(req) if have is None else have
    p, c = req.proposer_id, req.colleague_id
    if not (all((p, *s) in have for s in mine)
            and all((c, *s) in have for s in theirs)):
        return None
    cross = ([(c, *s) in have for s in mine]
             + [(p, *s) in have for s in theirs])
    if all(cross):
        return WORK
    if not any(cross):
        return PEOPLE
    return None


def _neither(req, have, mine, theirs):
    p, c = req.proposer, req.colleague
    facts = []
    for s in mine:
        has = (c.id, *s) in have
        facts.append(f"{c.name} {'already has a session' if has else 'has no session'} on {when(*s)}")
    for s in theirs:
        has = (p.id, *s) in have
        facts.append(f"{p.name} {'already has a session' if has else 'has no session'} on {when(*s)}")
    return ("This swap fits neither pattern — " + "; ".join(facts) + ". Either "
            "both GPs work both sessions and trade what they do in them, or "
            "neither works the other's and they cover for each other.")


def validate(req):
    """Why the swap cannot be applied as the rota stands: a list of
    sentences, empty when it can."""
    mine, theirs = sides(req)
    have = _entries(req)
    p, c = req.proposer, req.colleague
    names = {p.id: p.name, c.id: c.name}

    problems = [f"{p.name} has no session on {when(*s)}."
                for s in mine if (p.id, *s) not in have]
    problems += [f"{c.name} has no session on {when(*s)}."
                 for s in theirs if (c.id, *s) not in have]
    if problems:
        return problems

    k = kind(req, have)
    if k is None:
        return [_neither(req, have, mine, theirs)]

    # Paired sessions (mentoring) are two people's entries linked together;
    # neither half moves or changes.
    touched = [have[(p.id, *s)] for s in mine] + [have[(c.id, *s)] for s in theirs]
    if k == WORK:
        touched += [have[(c.id, *s)] for s in mine] + [have[(p.id, *s)] for s in theirs]
    seen = set()
    for e in touched:
        if e.companion_group and e.pk not in seen:
            seen.add(e.pk)
            problems.append(
                f"{names[e.clinician_id]}'s {when(e.day, e.part)} is a paired "
                "session (mentoring) and cannot be swapped.")

    # Neither GP may be on Breathe leave for a session they would take on:
    # the proposer takes on the colleague's side and vice versa.
    people = [p, c]
    days = [d for d, _ in mine + theirs]
    resolver = availability.AvailabilityResolver(
        PatternSlot.objects.filter(clinician__in=people),
        people,
        BreatheAbsence.objects.filter(clinician__in=people,
                                      start_date__lte=max(days), end_date__gte=min(days)),
        BreatheLeaveMapping.as_dict(),
    )
    for clinician, slots in ((p, theirs), (c, mine)):
        for day, part in slots:
            if resolver.on_leave(clinician.id, day, part):
                problems.append(
                    f"{clinician.name} is on leave on {when(day, part)} (from "
                    "Breathe) and cannot take that session.")
    return problems


def describe(req):
    """One sentence saying what applying the swap would do, or "" when the
    rota fits neither pattern."""
    k = kind(req)
    p, c = req.proposer, req.colleague
    mine, theirs = sides(req)
    if k == WORK:
        return f"{p.name} and {c.name} trade what they do on {_join(involved_slots(req))}."
    if k == PEOPLE:
        return (f"{c.name} takes {p.name}'s {_join(mine)}; "
                f"{p.name} takes {c.name}'s {_join(theirs)}.")
    return ""


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
    have = _entries(req)
    mine, theirs = sides(req)
    p, c = req.proposer, req.colleague
    if kind(req, have) == WORK:
        for day, part in involved_slots(req):
            e1, e2 = have[(p.id, day, part)], have[(c.id, day, part)]
            for attr in ("session_type", "site", "note", "allocation_group"):
                v1, v2 = getattr(e1, attr), getattr(e2, attr)
                setattr(e1, attr, v2)
                setattr(e2, attr, v1)
            e1.manually_set = e2.manually_set = True
            e1.save()
            e2.save()
            _log(actor, day, part, p.name, "swapped", f"with {c.name}")
    else:
        # PEOPLE: each entry changes hands and keeps what it is. The
        # receiver has no entry in that slot (that is what made it PEOPLE),
        # so the one-entry-per-cell constraint holds.
        for giver, taker, slots in ((p, c, mine), (c, p, theirs)):
            for day, part in slots:
                e = have[(giver.id, day, part)]
                e.clinician = taker
                e.manually_set = True
                e.save()
                _log(actor, day, part, taker.name, "swapped",
                     f"took over from {giver.name}")
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
