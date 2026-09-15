from collections import Counter
from dataclasses import dataclass

from django.db.models import Q

from rota.models import (BreatheAbsence, BreatheLeaveMapping, ClinicianGroup,
                         ClosedDay, CoverageRule, LocumRequirement, PatternSlot,
                         PracticeSettings, RotaEntry, SessionType)
from rota.services import calendar
from rota.services.availability import AvailabilityResolver
from rota.services.cells import cell_state


@dataclass
class Warning:
    code: str
    part: str | None
    message: str


@dataclass
class WarningBundle:
    """Everything day_warnings() and week_warnings() read that does not
    depend on the one day: fetched once by a caller rendering many days
    (the grid's eight-week window) and sliced per day. Without one the
    functions fetch for themselves, so the dashboard, the staffing report
    and the day view are unchanged."""
    entries_by_day: dict
    rules: list
    ceiling_types: list
    week_types: list
    groups: list
    settings: PracticeSettings
    open_weekdays: set
    closed: set
    locum_reqs: dict

    @classmethod
    def load(cls, days, include_drafts=True):
        entries = RotaEntry.objects.filter(day__in=days).select_related(
            "session_type", "clinician", "clinician__group",
            "entered_by", "entered_by__clinician")
        if not include_drafts:
            entries = entries.filter(is_published=True)
        by_day = {}
        for e in entries:
            by_day.setdefault(e.day, []).append(e)
        # First by pk, matching the .first() the unbundled path uses.
        reqs = {}
        for r in LocumRequirement.objects.filter(day__in=days).order_by("pk"):
            reqs.setdefault((r.day, r.part, r.session_type_id), r)
        settings = PracticeSettings.load()
        return cls(
            entries_by_day=by_day,
            rules=list(CoverageRule.objects.filter(
                frequency=CoverageRule.Frequency.PER_SLOT).select_related("session_type")),
            ceiling_types=list(SessionType.objects.filter(
                Q(max_per_session__isnull=False) | Q(max_per_day__isnull=False))),
            week_types=list(SessionType.objects.filter(max_per_week__isnull=False)),
            groups=list(ClinicianGroup.objects.filter(min_per_session__isnull=False)),
            settings=settings,
            open_weekdays=set(settings.open_weekday_list()),
            closed=set(ClosedDay.objects.filter(day__in=days).values_list("day", flat=True)),
            locum_reqs=reqs,
        )

    def is_open(self, day):
        return day.weekday() in self.open_weekdays and day not in self.closed


def _locum_suffix(day, part, session_type, bundle=None):
    if bundle is not None:
        req = bundle.locum_reqs.get((day, part, session_type.id))
    else:
        req = LocumRequirement.objects.filter(
            day=day, part=part, session_type=session_type).first()
    return f" — locum {req.get_status_display().lower()}" if req else ""


def _breathe_conflicts(day, entries, resolver=None):
    """Rostered sessions standing on a clinician Breathe says is off.

    Leave used to be approved in the rota, and approving it overwrote the
    entries. Breathe owns leave now and nothing overwrites anything, so the
    ordinary sequence — publish the week, then leave is approved in Breathe
    — leaves a published session against someone who is not coming in. The
    cell is ringed (cell_state's `clash`) and this line names who, with the
    kind of leave, so an admin can clear the session by hand.

    Decided by cell_state, so the header and the cell cannot disagree: an
    absence-category entry over Breathe leave is agreement, and an absence
    whose (kind, reason) has no mapping row is still leave.

    `resolver` is optional so the grid, which has already built one for the
    week, need not pay for another per day. Built here only for callers
    that have none.
    """
    if not entries:
        return []
    if resolver is None:
        clinicians = {e.clinician_id: e.clinician for e in entries}
        resolver = AvailabilityResolver(
            PatternSlot.objects.filter(clinician_id__in=clinicians),
            clinicians.values(),
            BreatheAbsence.objects.filter(clinician_id__in=clinicians,
                                          start_date__lte=day, end_date__gte=day),
            BreatheLeaveMapping.as_dict(),
        )
    warnings = []
    for part in ["AM", "PM"]:
        clashing = []
        for e in entries:
            if e.part != part:
                continue
            cell = cell_state(e.clinician_id, day, part, entry=e,
                              resolver=resolver, closed=False)
            if cell["clash"]:
                clashing.append((e.clinician.initials, e.clinician.name,
                                 cell["leave_label"]))
        if clashing:
            # Keyed by clinician, not initials: initials are free text with
            # no uniqueness constraint, and two different clinicians sharing
            # them both clashing must both be named, or the header would
            # disagree with the cells still ringing for each of them.
            who = ", ".join(f"{initials} ({label})"
                            for initials, name, label in sorted(clashing))
            warnings.append(Warning(
                "breathe", part, f"On Breathe leave but rostered ({part}): {who}"))
    return warnings


def day_warnings(day, include_drafts=True, resolver=None, bundle=None):
    """With a bundle, `include_drafts` is ignored: the bundle was already
    filtered to published-only (or not) at WarningBundle.load()."""
    if bundle is not None:
        if not bundle.is_open(day):
            return []
        entries = bundle.entries_by_day.get(day, [])
        rules, ceiling_types, groups = bundle.rules, bundle.ceiling_types, bundle.groups
        settings = bundle.settings
    else:
        if not calendar.is_open(day):
            return []
        entries = RotaEntry.objects.filter(day=day).select_related(
            "session_type", "clinician", "clinician__group",
            "entered_by", "entered_by__clinician"
        )
        if not include_drafts:
            entries = entries.filter(is_published=True)
        entries = list(entries)
        rules = CoverageRule.objects.filter(
            frequency=CoverageRule.Frequency.PER_SLOT).select_related("session_type")
        ceiling_types = SessionType.objects.filter(
            Q(max_per_session__isnull=False) | Q(max_per_day__isnull=False))
        groups = ClinicianGroup.objects.filter(min_per_session__isnull=False)
        settings = PracticeSettings.load()
    warnings = []

    for rule in rules:
        if not rule.applies_on(day):
            continue
        parts = ["AM", "PM"] if rule.unit == CoverageRule.Unit.PER_DAY else rule.parts_for()
        for part in parts:
            have = sum(
                1 for e in entries
                if e.part == part and e.session_type_id == rule.session_type_id
            )
            if have < rule.count:
                # Say how short: "No Routine cover" at three of four was
                # untrue, and the difference is what decides who to chase.
                text = (f"No {rule.session_type.name} cover ({part})" if have == 0
                        else f"{rule.session_type.name} {have}/{rule.count} ({part})")
                warnings.append(Warning(
                    "coverage", part,
                    text + _locum_suffix(day, part, rule.session_type, bundle),
                ))

    # Ceilings on a session type (docs/admin/session-types.md). Sessions, not
    # people: a full day is two, and "one Duty per day" is max_per_session
    # = 1, which caps each AM and PM at one.
    for st in ceiling_types:
        if st.max_per_session is not None:
            for part in ["AM", "PM"]:
                have = sum(1 for e in entries
                           if e.part == part and e.session_type_id == st.id)
                if have > st.max_per_session:
                    warnings.append(Warning(
                        "ceiling", part,
                        f"Too many {st.name} ({part}): {have}, max {st.max_per_session}"))
        if st.max_per_day is not None:
            have = sum(1 for e in entries if e.session_type_id == st.id)
            if have > st.max_per_day:
                warnings.append(Warning(
                    "ceiling", None,
                    f"Too many {st.name} today: {have} sessions, max {st.max_per_day}"))

    for part in ["AM", "PM"]:
        clinical = sum(
            1 for e in entries
            if e.part == part
            and e.session_type.category == SessionType.Category.CLINICAL
        )
        if clinical < settings.min_clinical_per_session:
            warnings.append(Warning(
                "staffing", part,
                f"Only {clinical} clinical GP(s) ({part})",
            ))

    for group in groups:
        for part in ["AM", "PM"]:
            present = sum(
                1 for e in entries
                if e.part == part
                and e.clinician.group_id == group.id
                and e.session_type.category != SessionType.Category.ABSENCE
            )
            if present < group.min_per_session:
                warnings.append(Warning(
                    "group", part,
                    f"{group.name}: {present}/{group.min_per_session} in ({part})",
                ))

    warnings.extend(_breathe_conflicts(day, entries, resolver))
    return warnings


def week_warnings(days, include_drafts=True, bundle=None):
    """The one ceiling that only makes sense across a week: a session
    type's max_per_week, over the open days given. Rendered in the week's
    header cell on the grid."""
    if bundle is not None:
        days = [d for d in days if bundle.is_open(d)]
        types = bundle.week_types
        if not days or not types:
            return []
        have = Counter(e.session_type_id for d in days
                       for e in bundle.entries_by_day.get(d, []))
    else:
        days = [d for d in days if calendar.is_open(d)]
        types = list(SessionType.objects.filter(max_per_week__isnull=False))
        if not days or not types:
            return []
        entries = RotaEntry.objects.filter(day__in=days, session_type__in=types)
        if not include_drafts:
            entries = entries.filter(is_published=True)
        have = Counter(entries.values_list("session_type_id", flat=True))
    return [
        Warning("ceiling", None,
                f"Too many {st.name} this week: {have[st.id]} sessions, max {st.max_per_week}")
        for st in types if have[st.id] > st.max_per_week
    ]
