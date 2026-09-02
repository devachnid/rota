from dataclasses import dataclass

from rota.models import (BreatheAbsence, BreatheLeaveMapping, ClinicianGroup,
                         CoverageRule, LocumRequirement, PatternSlot,
                         PracticeSettings, RotaEntry, SessionType)
from rota.services import calendar
from rota.services.availability import AvailabilityResolver


@dataclass
class Warning:
    code: str
    part: str | None
    message: str


def _locum_suffix(day, part, session_type):
    req = LocumRequirement.objects.filter(
        day=day, part=part, session_type=session_type
    ).first()
    return f" — locum {req.get_status_display().lower()}" if req else ""


def _breathe_conflicts(day, entries):
    """Rostered sessions standing on a clinician Breathe says is off.

    Leave used to be approved in the rota, and approving it overwrote the
    entries. Breathe owns leave now and nothing overwrites anything, so the
    ordinary sequence — publish the week, then leave is approved in Breathe —
    leaves a published session against someone who is not coming in. The cell
    still renders the session (an entry beats leave in cell_state, by design)
    and fill will not clear it (it never touches published or manual
    entries), so this warning is the only place the conflict surfaces. The
    admin clears the session by hand.

    Decided by the resolver, never by the mapping: an absence whose
    (kind, reason) has no mapping row renders no chip but is still leave.
    """
    if not entries:
        return []
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
        n = len({e.clinician_id for e in entries if e.part == part
                 and resolver.on_leave(e.clinician_id, day, part)})
        if n:
            warnings.append(Warning(
                "breathe", part, f"{n} rostered on Breathe leave ({part})"))
    return warnings


def day_warnings(day, include_drafts=True):
    if not calendar.is_open(day):
        return []
    entries = RotaEntry.objects.filter(day=day).select_related(
        "session_type", "clinician", "clinician__group"
    )
    if not include_drafts:
        entries = entries.filter(is_published=True)
    entries = list(entries)
    settings = PracticeSettings.load()
    warnings = []

    for rule in CoverageRule.objects.filter(
        frequency=CoverageRule.Frequency.PER_SLOT
    ).select_related("session_type"):
        if not rule.applies_on(day):
            continue
        parts = ["AM", "PM"] if rule.unit == CoverageRule.Unit.PER_DAY else rule.parts_for()
        for part in parts:
            have = sum(
                1 for e in entries
                if e.part == part and e.session_type_id == rule.session_type_id
            )
            if have < rule.count:
                warnings.append(Warning(
                    "coverage", part,
                    f"No {rule.session_type.name} cover ({part})"
                    + _locum_suffix(day, part, rule.session_type),
                ))

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

    for group in ClinicianGroup.objects.filter(min_per_session__isnull=False):
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

    warnings.extend(_breathe_conflicts(day, entries))
    return warnings
