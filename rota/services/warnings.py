from dataclasses import dataclass

from rota.models import (ClinicianGroup, CoverageRule, LocumRequirement,
                         PracticeSettings, RotaEntry, SessionType)
from rota.services import calendar


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
    return warnings
