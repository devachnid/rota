"""What the week grid shows: a window of weeks, and one row per clinician.

The page renders WEEKS_BEFORE weeks before the anchor Monday and
WEEKS_AFTER after it, in one table; Earlier and Later move the anchor by
STEP_WEEKS so successive windows overlap. The row builder is here rather
than in the view because the "entered in the clinical system" endpoint
re-renders one row through the same path, and the two must not drift.
"""

from datetime import date, timedelta

from django.db.models import Prefetch

from rota.models import (BreatheAbsence, BreatheLeaveMapping, Clinician,
                         ClinicianGroup, ClosedDay, DayNote, LocumRequirement,
                         PatternSlot, PracticeSettings, RotaEntry)
from rota.services import availability
from rota.services.cells import cell_state, day_note, one_block, shows_on_roster
from rota.services.warnings import WarningBundle, day_warnings, week_warnings

WEEKS_BEFORE = 1
WEEKS_AFTER = 6
STEP_WEEKS = 4


def _today():
    return date.today()


def week_monday(day):
    return day - timedelta(days=day.weekday())


def parse_anchor(raw, today=None):
    """The Monday of the week `?week=` names; today's week when it is
    absent or malformed."""
    try:
        anchor = date.fromisoformat(raw or "")
    except ValueError:
        anchor = today or _today()
    return week_monday(anchor)


class Window:
    def __init__(self, anchor, is_admin, user, today=None):
        self.anchor = anchor
        self.is_admin = is_admin
        self.user = user
        self.today = today or _today()
        settings = PracticeSettings.load()
        # sorted(): open_weekday_list() preserves input order, and the
        # per-week slices below take the first day of each week by value.
        offsets = sorted(settings.open_weekday_list())
        self.mondays = [anchor + timedelta(days=7 * i)
                        for i in range(-WEEKS_BEFORE, WEEKS_AFTER + 1)]
        self.days = sorted(m + timedelta(days=o) for m in self.mondays for o in offsets)
        # min()/max(), not [0]/[-1]: `days` can be empty (open_weekdays ""
        # parses to [] and PracticeSettings.clean() accepts it).
        self.start = min(self.days) if self.days else anchor
        self.end = max(self.days) if self.days else anchor
        self.week_starts = set()
        for m in self.mondays:
            in_week = [d for d in self.days if week_monday(d) == m]
            if in_week:
                self.week_starts.add(min(in_week))
        self._bundle = None
        self._load()

    def _load(self):
        days = self.days
        entries = RotaEntry.objects.filter(day__in=days).select_related(
            "session_type", "clinician", "site", "entered_by", "entered_by__clinician")
        if not self.is_admin:
            entries = entries.filter(is_published=True)
        self.entries = list(entries)
        self.cell_map = {(e.clinician_id, e.day, e.part): e for e in self.entries}

        self.companion_partner = {}
        by_group = {}
        for e in self.entries:
            if e.companion_group:
                by_group.setdefault(e.companion_group, []).append(e)
        for pair in by_group.values():
            if len(pair) != 2:
                continue
            e1, e2 = pair
            self.companion_partner[(e1.clinician_id, e1.day, e1.part)] = e2.clinician.name
            self.companion_partner[(e2.clinician_id, e2.day, e2.part)] = e1.clinician.name

        self.active = list(Clinician.objects.filter(active=True))
        pattern_rows = list(PatternSlot.objects.filter(
            clinician__in=self.active).order_by("effective_from"))
        absences = BreatheAbsence.objects.none()
        if days:
            absences = BreatheAbsence.objects.filter(
                clinician__in=self.active,
                start_date__lte=self.end, end_date__gte=self.start)
        self.resolver = availability.AvailabilityResolver(
            pattern_rows, self.active, absences, BreatheLeaveMapping.as_dict())
        self.closed = set(ClosedDay.objects.filter(day__in=days)
                          .values_list("day", flat=True))
        self.notes = {n.day: n for n in DayNote.objects.filter(day__in=days)}

    # ---- header --------------------------------------------------------

    def bundle(self):
        """One WarningBundle per page, shared by weeks() and day_headers();
        None for a non-admin, who sees no warnings."""
        if self._bundle is None and self.is_admin:
            self._bundle = WarningBundle.load(self.days)
        return self._bundle

    def weeks(self):
        bundle = self.bundle()
        out = []
        for m in self.mondays:
            in_week = [d for d in self.days if week_monday(d) == m]
            if not in_week:
                continue
            drafts = sum(1 for e in self.entries
                         if week_monday(e.day) == m and not e.is_published)
            out.append({
                "monday": m,
                "end": max(in_week),
                "colspan": len(in_week) * 2,
                "drafts": drafts,
                "is_anchor": m == self.anchor,
                "warnings": (week_warnings(in_week, include_drafts=True, bundle=bundle)
                             if self.is_admin else []),
            })
        return out

    def day_headers(self):
        bundle = self.bundle()
        return [
            {"day": d, "closed": d in self.closed, "note": self.notes.get(d),
             "week_start": d in self.week_starts, "today": d == self.today,
             "warnings": (day_warnings(d, include_drafts=True, resolver=self.resolver,
                                       bundle=bundle) if self.is_admin else [])}
            for d in self.days
        ]

    # ---- body ----------------------------------------------------------

    def build_row(self, clinician, is_locum):
        """One clinician's row, or None when the roster rule hides them."""
        has_entry = any((clinician.id, d, part) in self.cell_map
                        for d in self.days for part in ("AM", "PM"))
        in_service = any(self.resolver.in_service(clinician.id, d) for d in self.days)
        if not shows_on_roster(is_locum=is_locum, has_entry=has_entry,
                               in_service=in_service):
            return None
        cells = []
        for d in self.days:
            am, pm = (cell_state(
                clinician.id, d, part,
                entry=self.cell_map.get((clinician.id, d, part)),
                resolver=self.resolver, closed=d in self.closed,
                partner=self.companion_partner.get((clinician.id, d, part)),
            ) for part in ("AM", "PM"))
            flags = {"week_start": d in self.week_starts, "today": d == self.today}
            if one_block(am, pm):
                # One chip across both columns; its form edits the whole
                # day (part "DAY") unless the admin picks a half.
                cells.append({**am, "part": "DAY", "merged": True,
                              "note": day_note(am, pm), **flags})
            else:
                cells.append({**am, "merged": False, **flags})
                cells.append({**pm, "merged": False, "week_start": False,
                              "today": d == self.today})
        return {
            "clinician": clinician,
            "mine": clinician.user_id == self.user.id,
            "cells": cells,
        }

    def sections(self):
        groups = ClinicianGroup.objects.prefetch_related(
            Prefetch("clinicians", queryset=Clinician.objects.filter(active=True)
                     .order_by("display_order", "name")))
        out = []
        for group in groups:
            rows = [row for row in (self.build_row(c, group.is_locum_group)
                                    for c in group.clinicians.all()) if row]
            if rows or group.is_locum_group:
                out.append({"group": group, "rows": rows})
        return out

    def locum_cells(self):
        reqs = LocumRequirement.objects.filter(day__in=self.days).select_related(
            "session_type", "covering")
        req_map = {}
        for r in reqs:
            req_map.setdefault((r.day, r.part), []).append(r)
        return [
            {"day": d, "day_str": d.isoformat(), "part": part,
             "reqs": req_map.get((d, part), []),
             "week_start": d in self.week_starts and part == "AM",
             "today": d == self.today}
            for d in self.days for part in ("AM", "PM")
        ]
