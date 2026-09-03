"""What a rota cell shows, decided once.

    entry exists                -> the entry
    on leave and showable       -> the Breathe absence (`absence`, mapped)
    on leave, mapped or not     -> `on_leave`, entry or no entry
    entry AND on leave          -> `clash`, unless the entry is itself an absence
    works_on                    -> not off: here, nothing allocated
    otherwise                   -> off: not here

The week grid, the day view and My Schedule all render cells, and a second
copy of this would be a second answer to the question the availability
consolidation existed to give one answer to.
"""

from rota.models import SessionType


def leave_label(kind, reason):
    """The words for a Breathe absence — a tooltip, a warning line.

    Never goes through the mapping: an absence whose kind has lost its
    mapping row renders no chip, but it is still leave and still says which.
    Sickness carries no reason by construction (the type is health data and
    is never stored), so "Sick" is all it can ever say.
    """
    if kind == "holiday":
        return "Holiday"
    if kind == "sickness":
        return "Sick"
    if kind == "other":
        return f"Other leave: {reason}" if reason else "Other leave"
    return kind.capitalize()


def cell_state(clinician_id, day, part, *, entry, resolver, closed,
               partner=None):
    """One cell's state. Performs no queries — the caller prefetches."""
    works = resolver.works_on(clinician_id, day, part)
    covering = resolver.covering(clinician_id, day, part)
    # Two different questions, and they must not be answered by one value:
    # `absence` is what to *render* on an empty cell and goes through the
    # mapping, so a kind with no mapping row is None; `on_leave` is whether
    # Breathe says the clinician is off, never touches the mapping, and is
    # answered whether or not an entry stands on the cell. It used to be
    # forced False under an entry — which is exactly why a published
    # session over later-approved leave could not be marked anywhere.
    on_leave = covering is not None
    leave_type = resolver.leave_type(clinician_id, day, part) if entry is None else None

    # A rostered session on someone Breathe says is off. An absence-category
    # entry (an admin marking AL by hand) over Breathe leave is agreement,
    # not a clash.
    clash = (entry is not None and on_leave
             and entry.session_type.category != SessionType.Category.ABSENCE)

    # Show the absence only where it means something: on a session the
    # clinician works, or for a clinician with no pattern at all (nothing
    # would ever show for them otherwise). Showing it on every session a
    # leave span covers would put chips on every part-timer's days off —
    # a part-timer's day off must not read "AL" on a day they never work.
    #
    # Two things the "no pattern" clause must not skip:
    #  - the contractual window. `works` already carries the window; the
    #    no-pattern branch has to ask separately, or a chip would show for a
    #    week the clinician was never employed for.
    #  - a closed day. A bank holiday inside a leave range correctly has no
    #    entry, and a chip there is noise on every Christmas closure.
    no_pattern_here = (not resolver.has_pattern(clinician_id)
                       and resolver.in_service(clinician_id, day))
    showable = (works or no_pattern_here) and not closed

    return {
        "day": day,
        "day_str": day.isoformat(),
        "part": part,
        "entry": entry,
        "off": entry is None and not works,
        "absence": leave_type if showable else None,
        "on_leave": on_leave,
        "leave_label": leave_label(*covering) if covering else None,
        "clash": clash,
        "closed": closed,
        "partner": partner,
    }
