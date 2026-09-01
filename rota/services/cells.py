"""What a rota cell shows, decided once.

    entry exists                -> the entry
    on leave and ghostable      -> a ghosted leave chip
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
    leave_type = resolver.leave_type(clinician_id, day) if entry is None else None

    # Ghost only where it means something: on a session the clinician works
    # (approval should have written an entry and did not), or for a clinician
    # with no pattern at all (nothing would ever show for them otherwise).
    # Ghosting every session leave spans would put chips on every part-timer's
    # days off.
    #
    # Two things the "no pattern" clause must not skip:
    #  - the contractual window. leave.sessions_affected() and works_on() both
    #    refuse to write outside it, so a chip there accuses approval of
    #    missing an entry it was right not to write. `works` already carries
    #    the window; the no-pattern branch has to ask separately.
    #  - a closed day. sessions_affected() skips days where calendar.is_open()
    #    is false, so a bank holiday inside a leave range correctly has no
    #    entry, and a ghost there is noise on every Christmas closure.
    no_pattern_here = (not resolver.has_pattern(clinician_id)
                       and resolver.in_service(clinician_id, day))
    ghostable = (works or no_pattern_here) and not closed

    return {
        "day": day,
        "day_str": day.isoformat(),
        "part": part,
        "entry": entry,
        "off": entry is None and not works,
        "ghost_leave": leave_type if ghostable else None,
        "closed": closed,
        "partner": partner,
    }
