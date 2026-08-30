def impact_score(ctx, day, part):
    """How thick would Routine cover be here: the number of active
    clinicians who are pattern-available at (day, part) and still have a
    free cell there. Used to place non-routine sessions (e.g. trainee SDL)
    where absorbing one costs the least appointment capacity.
    """
    return sum(
        1 for c in ctx.clinicians
        if ctx.available(c.id, day, part) and ctx.is_free(c.id, day, part)
    )
