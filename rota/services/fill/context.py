from datetime import timedelta

from rota.models import (Clinician, PatternSlot, PracticeSettings, RotaEntry,
                         SessionType, TraineeStageRule)
from rota.services import availability, calendar, fairness


class FillContext:
    """Prefetches everything the fill engine reads per-candidate-per-slot in
    v1 (availability, existing entries, per-type/day/part counts, per-day
    held types, session-type eligibility and same-day blocks) so the fill
    passes can answer those questions from memory instead of hitting the DB
    in inner loops.
    """

    def __init__(self, start, end):
        self.start = start
        self.end = end

        self.clinicians = list(Clinician.objects.filter(active=True).order_by("name"))
        self.by_id = {c.id: c for c in self.clinicians}
        self._active_ids = set(self.by_id)

        pattern_rows = PatternSlot.objects.filter(
            clinician__in=self.clinicians
        ).order_by("effective_from")
        self._pattern_resolver = availability.PatternResolver(pattern_rows)

        self._cells = {}
        self._type_count = {}
        self._day_types = {}
        self._clinician_type_count = {}
        for entry in RotaEntry.objects.filter(day__range=(start, end)):
            self._index_entry(entry)

        session_types = SessionType.objects.all().prefetch_related(
            "allowed_clinicians", "allowed_groups", "blocks_same_day"
        )
        self._allowed = {}
        self._blocks = {}
        self.fairness_type_ids = set()
        for st in session_types:
            allowed_clinicians = list(st.allowed_clinicians.all())
            allowed_groups = list(st.allowed_groups.all())
            if not allowed_clinicians and not allowed_groups:
                self._allowed[st.id] = None
            else:
                group_ids = {g.id for g in allowed_groups}
                # An M2M row for a clinician who has since been
                # deactivated must not leak into eligible_ids() — the
                # group-membership half below is already scoped to
                # self.clinicians, which is active-only. The "is this
                # type restricted at all" check just above stays
                # unfiltered (matches SessionType.is_eligible()): a type
                # whose only individually-allowed clinician has gone
                # inactive is still restricted, just to nobody, not
                # silently unrestricted.
                ids = {c.id for c in allowed_clinicians if c.active}
                ids |= {c.id for c in self.clinicians if c.group_id in group_ids}
                self._allowed[st.id] = ids
            self._blocks[st.id] = {t.id for t in st.blocks_same_day.all()}
            if st.fairness_tracked:
                self.fairness_type_ids.add(st.id)

        self.settings = PracticeSettings.load()
        self.weights = fairness.weights(end)

        # Four rows of reference data, read once per profile per trainee pass
        # (VTS, SDL, mentoring) — three queries per trainee without this.
        # Passed to TraineeProfile.weekly_rates(); a stage missing from the
        # mapping yields None, the same as a deleted row.
        self.stage_rules = {r.stage: r for r in TraineeStageRule.objects.all()}

        self.open_days = []
        d = start
        while d <= end:
            if calendar.is_open(d):
                self.open_days.append(d)
            d += timedelta(days=1)
        self.open_day_set = set(self.open_days)

    def _index_entry(self, entry):
        self._cells[(entry.clinician_id, entry.day, entry.part)] = entry
        key = (entry.session_type_id, entry.day, entry.part)
        self._type_count[key] = self._type_count.get(key, 0) + 1
        self._day_types.setdefault(
            (entry.clinician_id, entry.day), set()
        ).add(entry.session_type_id)
        ct_key = (entry.clinician_id, entry.session_type_id)
        self._clinician_type_count[ct_key] = (
            self._clinician_type_count.get(ct_key, 0) + 1)

    def works_on(self, cid, day, part):
        return self._pattern_resolver.works_on(cid, day, part)

    def is_free(self, cid, day, part):
        return (cid, day, part) not in self._cells

    def count_type(self, st_id, day, part):
        return self._type_count.get((st_id, day, part), 0)

    def clinician_type_count(self, cid, st_id):
        """Count of this session type already on the rota for this
        clinician, anywhere in [self.start, self.end] — includes entries
        present at prefetch time (e.g. published from an earlier fill) plus
        any recorded via record() so far in this pass."""
        return self._clinician_type_count.get((cid, st_id), 0)

    def day_type_ids(self, cid, day):
        return self._day_types.get((cid, day), set())

    def eligible_ids(self, st):
        ids = self._allowed.get(st.id)
        return self._active_ids if ids is None else ids

    def blocked(self, cid, day, st):
        held = self.day_type_ids(cid, day)
        return any(st.id in self._blocks.get(tid, set()) for tid in held)

    def record(self, entry):
        self._index_entry(entry)

    def weeks(self):
        first_monday = self.start - timedelta(days=self.start.weekday())
        last_monday = self.end - timedelta(days=self.end.weekday())
        out = []
        d = first_monday
        while d <= last_monday:
            out.append(d)
            d += timedelta(days=7)
        return out
