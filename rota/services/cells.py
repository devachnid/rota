"""What a rota cell shows, decided once.

    entry exists                -> the entry
    on leave and showable       -> the Breathe absence (`absence`, mapped)
    on leave, mapped or not     -> `on_leave`, which nothing renders
    works_on                    -> not off: here, nothing allocated
    otherwise                   -> off: not here

The week grid and the day view both render cells, and a second copy of this
would be a second answer to the question the availability consolidation
existed to give one answer to.
"""


def cell_state(clinician_id, day, part, *, entry, resolver, closed,
               partner=None):
    """One cell's state. Performs no queries — the caller prefetches."""
    works = resolver.works_on(clinician_id, day, part)
    leave_type = resolver.leave_type(clinician_id, day, part) if entry is None else None
    # Two different questions, and they must not be answered by one value:
    # `absence` is what to *render* and goes through the mapping, so a kind
    # with no mapping row is None; `on_leave` is whether Breathe says the
    # clinician is off, and never touches the mapping. Every consumer that
    # counts or files people — the day view's partition, My Schedule's week
    # label — asks this one, or deleting a mapping row would turn a sick
    # clinician back into "in".
    on_leave = resolver.on_leave(clinician_id, day, part) if entry is None else False

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
        "closed": closed,
        "partner": partner,
    }
