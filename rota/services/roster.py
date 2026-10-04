"""Who is in on a day: the day view's roster, and the phone week's five.

One place decides it, because two screens answering "who is on leave on
Tuesday" separately is two chances to disagree. RosterSource fetches what a
run of days needs in one go — the entries, the clinicians and their
patterns, Breathe leave, closures and day notes — and day() builds one
day's lists from it without a query of its own, so five days cost what one
does. The rules themselves moved here from rota/views/day.py unchanged.
"""

from dataclasses import dataclass, field
from datetime import date

from rota.models import (BreatheAbsence, BreatheLeaveMapping, Clinician,
                         ClosedDay, DayNote, PatternSlot, PracticeSettings,
                         RotaEntry, SessionType)
from rota.services import availability
from rota.services.cells import (cell_state, day_note, one_block,
                                 shows_on_roster)


@dataclass
class DayRoster:
    day: date
    is_closed: bool
    closed_reason: str
    show_body: bool
    roster: list = field(default_factory=list)    # {"clinician", "cells"}
    on_leave: list = field(default_factory=list)  # {"clinician", "cells"}
    not_in: list = field(default_factory=list)    # Clinician
    pinned: list = field(default_factory=list)    # {"clinician", "entry", "note", "part", "clash", "leave_label"}
    note: DayNote | None = None

    @property
    def in_count(self):
        return len(self.roster)

    @property
    def leave_count(self):
        return len(self.on_leave)


class RosterSource:
    def __init__(self, days, *, include_drafts):
        self.days = sorted(days)
        settings = PracticeSettings.load()
        self.open_weekdays = set(settings.open_weekday_list())

        entries = RotaEntry.objects.filter(day__in=self.days).select_related(
            "session_type", "clinician", "site", "entered_by", "entered_by__clinician")
        if not include_drafts:
            entries = entries.filter(is_published=True)
        self.entries = list(entries)
        self.by_clinician_day = {}
        for e in self.entries:
            self.by_clinician_day.setdefault((e.clinician_id, e.day), {})[e.part] = e

        self.partner = {}
        groups = {}
        for e in self.entries:
            if e.companion_group:
                groups.setdefault(e.companion_group, []).append(e)
        for pair in groups.values():
            if len(pair) == 2:
                a, b = pair
                self.partner[(a.clinician_id, a.day, a.part)] = b.clinician.name
                self.partner[(b.clinician_id, b.day, b.part)] = a.clinician.name

        self.active = list(Clinician.objects.filter(active=True)
                           .select_related("group").order_by("display_order", "name"))
        pattern_rows = list(PatternSlot.objects.filter(clinician__in=self.active))
        absences = BreatheAbsence.objects.none()
        if self.days:
            absences = BreatheAbsence.objects.filter(
                clinician__in=self.active,
                start_date__lte=max(self.days), end_date__gte=min(self.days))
        self.resolver = availability.AvailabilityResolver(
            pattern_rows, self.active, absences, BreatheLeaveMapping.as_dict())

        self.closures = {cd.day: cd.reason
                         for cd in ClosedDay.objects.filter(day__in=self.days)}
        self.notes = {n.day: n for n in DayNote.objects.filter(day__in=self.days)}

    def day(self, target):
        is_closed = (target in self.closures
                     or target.weekday() not in self.open_weekdays)
        resolver = self.resolver
        result = DayRoster(day=target, is_closed=is_closed,
                           closed_reason=self.closures.get(target, ""),
                           show_body=False, note=self.notes.get(target))
        shown_cells = []  # every listed clinician's cells, for the pinned block
        absence = SessionType.Category.ABSENCE
        for c in self.active:
            mine = self.by_clinician_day.get((c.id, target), {})
            if not shows_on_roster(is_locum=c.group.is_locum_group,
                                   has_entry=bool(mine),
                                   in_service=resolver.in_service(c.id, target)):
                continue
            cells = [
                cell_state(c.id, target, part, entry=mine.get(part),
                           resolver=resolver, closed=is_closed,
                           partner=self.partner.get((c.id, target, part)))
                for part in ("AM", "PM")
            ]
            # On-leave means every part the clinician works is covered — either
            # by a Breathe absence for this day/part, or (for history predating
            # the overlay) by an absence-category entry. A cell is "off" when
            # nothing is expected there at all (cell_state already worked that
            # out); a part where off is False is a part they work, and it needs
            # one of those two to count as covered. A clinician with no worked
            # parts at all (nothing to cover) is never "on leave" — that's
            # not_in below.
            #
            # `on_leave`, not `absence`: `absence` is the mapped chip, so with a
            # kind's default mapping row missing, a sick clinician read "1 in ·
            # 0 on leave" — the count and the scheduler disagreeing about the
            # same person. What renders is still `absence`; what is counted is
            # what Breathe said.
            worked_cells = [cell for cell in cells if not cell["off"]]
            is_on_leave = bool(worked_cells) and all(
                cell["on_leave"]
                or (cell["entry"] and cell["entry"].session_type.category == absence)
                for cell in worked_cells
            )
            # Drawn as the grid draws it: matching halves are one chip across
            # both columns, with the two notes folded into one line.
            am, pm = cells
            if one_block(am, pm):
                drawn = [{**am, "part": "DAY", "merged": True,
                          "note": day_note(am, pm)}]
            else:
                drawn = [{**am, "merged": False}, {**pm, "merged": False}]
            shown_cells.append((c, drawn))
            if is_on_leave:
                result.on_leave.append({"clinician": c, "cells": drawn})
            elif mine or any(not cell["off"] or cell["absence"] for cell in cells):
                # cell["absence"] alone (off True, no entry) is the "no pattern
                # entered yet" case: cell_state shows it precisely because
                # nothing else would ever show for that clinician. The grid
                # renders that chip too; filing them under "Not in" instead
                # would drop the integrity warning and assert a lie — that they
                # do not work this day — when the truth is nobody has entered
                # their pattern.
                result.roster.append({"clinician": c, "cells": drawn})
            else:
                result.not_in.append(c)

        # Built from the drawn cells rather than the raw entries so a pinned
        # type one person holds all day is one row saying so, not an AM row
        # and a PM row. Every entry belongs to a listed clinician (an entry
        # earns its clinician a row whatever their dates say), so nothing is
        # lost by starting from the rows.
        #
        # The clash travels with the pin: someone rostered on Duty whom
        # Breathe says is off is on the pinned line, and a line reading "on
        # Duty" with no sign of it names someone who will not be there.
        result.pinned = sorted(
            ({"clinician": c, "entry": cell["entry"], "note": cell["note"],
              "part": "All day" if cell["merged"] else cell["part"],
              "clash": cell["clash"], "leave_label": cell["leave_label"]}
             for c, drawn in shown_cells for cell in drawn
             if cell["entry"] and cell["entry"].session_type.pin_on_day_view),
            key=lambda r: (r["entry"].session_type.name, r["clinician"].name,
                           r["entry"].part),
        )

        # A closure statement is true and worth showing, but it is not a reason
        # to withhold rostered work: when the day carries real RotaEntry rows,
        # the body renders alongside the closure line, not instead of it. This
        # is deliberately keyed on the day's entries, not on `roster` being
        # non-empty — a clinician whose pattern says they work a closed Tuesday
        # still lands in `roster` as a dash row even with zero entries that
        # day, and that must not be enough to light up the body on its own.
        # Only a closed day with no entries at all keeps the old behaviour —
        # the closure line alone, and the header count line suppressed along
        # with the body it would otherwise describe.
        has_entries = any(e.day == target for e in self.entries)
        result.show_body = not is_closed or has_entries
        return result
