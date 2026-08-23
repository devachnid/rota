from rota.models import Part, PatternSlot


def _current_slot(clinician, weekday, part, as_of):
    return (
        PatternSlot.objects.filter(
            clinician=clinician, weekday=weekday, part=part, effective_from__lte=as_of
        )
        .order_by("-effective_from")
        .first()
    )


def works_on(clinician, day, part):
    slot = _current_slot(clinician, day.weekday(), part, day)
    return bool(slot and slot.works)


class PatternResolver:
    """Batched equivalent of works_on(), built once from a prefetched set of
    PatternSlot rows so callers that ask the same question many times (the
    fill engine's inner loops, the grid view's per-cell render) don't issue
    a query per lookup.

    Applies the same rule as works_on(): for a given clinician, weekday and
    part, the row with the greatest effective_from on or before the day
    decides; no matching row means not working.
    """

    def __init__(self, pattern_rows):
        self._by_key = {}
        for row in sorted(pattern_rows, key=lambda r: r.effective_from):
            self._by_key.setdefault(
                (row.clinician_id, row.weekday, row.part), []
            ).append(row)

    def works_on(self, clinician_id, day, part):
        current = None
        for row in self._by_key.get((clinician_id, day.weekday(), part), []):
            if row.effective_from <= day:
                current = row
        return bool(current and current.works)


def weekly_sessions(clinician, as_of):
    return sum(
        1
        for weekday in range(7)
        for part in Part.values
        if (s := _current_slot(clinician, weekday, part, as_of)) and s.works
    )
