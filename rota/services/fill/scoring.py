def impact_score(ctx, day, part):
    """How thick would Routine cover be here: the number of clinicians who
    are available at (day, part) — active, inside their contractual window,
    working that session by their pattern, and not on approved leave — and
    who still have a free cell there. Used to place non-routine sessions
    (e.g. trainee SDL) where absorbing one costs the least appointment
    capacity.
    """
    return sum(
        1 for c in ctx.clinicians
        if ctx.available(c.id, day, part) and ctx.is_free(c.id, day, part)
    )
