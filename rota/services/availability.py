from rota.models import Part, PatternSlot
from rota.services.breathe.halfdays import parts_off


def _current_slot(clinician, weekday, part, as_of):
    return (
        PatternSlot.objects.filter(
            clinician=clinician, weekday=weekday, part=part, effective_from__lte=as_of
        )
        .order_by("-effective_from")
        .first()
    )


def in_service(clinician, day):
    """Active and inside the contractual window on `day`.

    The two clinician-level halves of the availability question, with the
    pattern and leave left out. Everything that asks "is this person one of
    ours on this date?" — the pattern-free ghost clause on the grid, the
    fairness pool, weekly_sessions — must ask it here rather than testing
    `active` alone, which is what let a clinician past their end_date keep
    full fairness weight.
    """
    return bool(clinician.active and clinician.in_window(day))


def works_on(clinician, day, part):
    """Single-clinician availability. Issues queries; use AvailabilityResolver
    for anything that asks repeatedly.

    Checks the same three things the resolver does — active, the contractual
    window, then the pattern — so `leave.sessions_affected()` cannot write
    leave outside a clinician's window while the grid hides it.
    """
    if not in_service(clinician, day):
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
    """How many sessions a week this clinician's pattern gives them as of
    `as_of` — and nothing at all if they are not in service on that date.

    fairness.weights() and fairness.fair_shares() are built on this, and were
    the last consumer still asking `active` alone. A clinician past their
    end_date but still flagged active — exactly the state the two separate
    fields invite — carried full weight: a share on the fairness report they
    can never work, a balance sinking further every week, and a denominator
    in coverage._pick() that diluted every real candidate's share.
    """
    if not in_service(clinician, as_of):
        return 0
    return sum(
        1
        for weekday in range(7)
        for part in Part.values
        if (s := _current_slot(clinician, weekday, part, as_of)) and s.works
    )


class AvailabilityResolver:
    """The one answer to "can this clinician be given this session?".

    Composes, cheapest check first: `active`, the contractual date window, the
    working pattern, then Breathe absences. All four are read at one moment by
    one call, so they cannot disagree — which is the risk in `active` and the
    date window being separate concepts.

    Built once per request or per fill from prefetched rows; every lookup is
    in memory.
    """

    def __init__(self, pattern_rows, clinicians, absences, mapping=None):
        # Built from prefetched rows, so the caller's iterable shape must not
        # matter. pattern_rows is walked twice below (once by PatternResolver,
        # once to build _with_pattern) — a one-shot generator would silently
        # leave _with_pattern empty and has_pattern() False for everyone.
        pattern_rows = list(pattern_rows)
        self._patterns = PatternResolver(pattern_rows)
        self._clinicians = {c.id: c for c in clinicians}
        self._with_pattern = {row.clinician_id for row in pattern_rows}

        # {clinician_id: [(span, session_type), ...]} from the Breathe overlay.
        # The mapping (kind, reason) -> type is resolved here, once, so a
        # lookup never touches the database. Exact reason first, then the
        # kind's default row; an unmapped kind renders nothing rather than
        # crashing, and the sync status page is where that gets noticed.
        mapping = mapping or {}
        self._leave = {}
        for a in absences:
            session_type = (mapping.get((a.kind, a.reason))
                            or mapping.get((a.kind, "")))
            if session_type is None:
                continue
            self._leave.setdefault(a.clinician_id, []).append((a.span, session_type))

    def has_pattern(self, clinician_id):
        """Whether any pattern row exists at all. Distinct from "does not work
        this session" — Task 5's ghosting rule needs to tell them apart."""
        return clinician_id in self._with_pattern

    def in_service(self, clinician_id, day):
        """Active and inside the contractual window — works_on() without the
        pattern, for callers whose question does not involve one. The grid's
        no-pattern ghost clause is exactly that: a clinician with no pattern
        rows at all still must not be ghosted on a date they are not
        employed for."""
        clinician = self._clinicians.get(clinician_id)
        return clinician is not None and in_service(clinician, day)

    def works_on(self, clinician_id, day, part):
        if not self.in_service(clinician_id, day):
            return False
        return self._patterns.works_on(clinician_id, day, part)

    def leave_type(self, clinician_id, day, part):
        """The absence type covering `day`/`part`, or None. Part-aware:
        Breathe records half-days, and the rota's parts are the unit."""
        for span, session_type in self._leave.get(clinician_id, ()):
            if part in parts_off(span, day):
                return session_type
        return None

    def on_leave(self, clinician_id, day, part):
        return self.leave_type(clinician_id, day, part) is not None

    def available(self, clinician_id, day, part):
        return (self.works_on(clinician_id, day, part)
                and not self.on_leave(clinician_id, day, part))
