from rota.models import LeaveRequest, Part, PatternSlot


def _current_slot(clinician, weekday, part, as_of):
    return (
        PatternSlot.objects.filter(
            clinician=clinician, weekday=weekday, part=part, effective_from__lte=as_of
        )
        .order_by("-effective_from")
        .first()
    )


def works_on(clinician, day, part):
    """Single-clinician availability. Issues queries; use AvailabilityResolver
    for anything that asks repeatedly.

    Checks the same three things the resolver does — active, the contractual
    window, then the pattern — so `leave.sessions_affected()` cannot write
    leave outside a clinician's window while the grid hides it.
    """
    if not clinician.active or not clinician.in_window(day):
        return False
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


class AvailabilityResolver:
    """The one answer to "can this clinician be given this session?".

    Composes, cheapest check first: `active`, the contractual date window, the
    working pattern, then approved leave. All four are read at one moment by
    one call, so they cannot disagree — which is the risk in `active` and the
    date window being separate concepts.

    Built once per request or per fill from prefetched rows; every lookup is
    in memory.
    """

    def __init__(self, pattern_rows, clinicians, leave_requests):
        # Built from prefetched rows, so the caller's iterable shape must not
        # matter. pattern_rows is walked twice below (once by PatternResolver,
        # once to build _with_pattern) — a one-shot generator would silently
        # leave _with_pattern empty and has_pattern() False for everyone.
        pattern_rows = list(pattern_rows)
        self._patterns = PatternResolver(pattern_rows)
        self._clinicians = {c.id: c for c in clinicians}
        self._with_pattern = {row.clinician_id for row in pattern_rows}

        # {clinician_id: [(start, end, session_type), ...]} for approved leave
        self._leave = {}
        for req in leave_requests:
            if req.status != LeaveRequest.Status.APPROVED:
                continue
            self._leave.setdefault(req.clinician_id, []).append(
                (req.start_date, req.end_date, req.session_type))

    def has_pattern(self, clinician_id):
        """Whether any pattern row exists at all. Distinct from "does not work
        this session" — Task 5's ghosting rule needs to tell them apart."""
        return clinician_id in self._with_pattern

    def works_on(self, clinician_id, day, part):
        clinician = self._clinicians.get(clinician_id)
        if clinician is None or not clinician.active:
            return False
        if not clinician.in_window(day):
            return False
        return self._patterns.works_on(clinician_id, day, part)

    def leave_type(self, clinician_id, day):
        """The SessionType of approved leave covering `day`, or None.

        Requests store dates, not parts, so leave is whole-day across its
        range and `part` does not enter into it.
        """
        for start, end, session_type in self._leave.get(clinician_id, ()):
            if start <= day <= end:
                return session_type
        return None

    def on_leave(self, clinician_id, day, part):
        return self.leave_type(clinician_id, day) is not None

    def available(self, clinician_id, day, part):
        return (self.works_on(clinician_id, day, part)
                and not self.on_leave(clinician_id, day, part))
