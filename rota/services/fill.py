from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db import transaction

from rota.models import (Clinician, CoverageRule, PracticeSettings, RotaEntry)
from rota.services import availability, calendar, entries, fairness

WINDOW_DAYS = 91


@dataclass
class UnfilledSlot:
    day: date
    part: str | None
    session_type: str
    reason: str


@dataclass
class FillResult:
    created: int = 0
    unfilled: list[UnfilledSlot] = field(default_factory=list)


def _days(start, end):
    d = start
    while d <= end:
        if calendar.is_open(d):
            yield d
        d += timedelta(days=1)


def _cell_free(clinician, day, part):
    return not RotaEntry.objects.filter(
        clinician=clinician, day=day, part=part
    ).exists()


def _has_fairness_entry(clinician, day):
    return RotaEntry.objects.filter(
        clinician=clinician, day=day, session_type__fairness_tracked=True
    ).exists()


def _eligible(clinician, day, parts, session_type):
    return (
        all(availability.works_on(clinician, day, p) for p in parts)
        and all(_cell_free(clinician, day, p) for p in parts)
        and session_type.is_eligible(clinician)
        and not (session_type.fairness_tracked and _has_fairness_entry(clinician, day))
    )


@transaction.atomic
def run_fill(actor, start, end, fill_default=False):
    RotaEntry.objects.filter(
        day__range=(start, end), is_published=False, manually_set=False
    ).delete()

    result = FillResult()
    clinicians = list(Clinician.objects.filter(active=True).order_by("name"))
    weights = fairness.weights(end)
    total_weight = sum(weights.values()) or 1

    for rule in CoverageRule.objects.select_related("session_type").order_by(
        "priority", "id"
    ):
        st = rule.session_type
        actuals = fairness.counts(st, start - timedelta(days=WINDOW_DAYS),
                                  start - timedelta(days=1))
        total_assigned = sum(actuals.values())
        last = fairness.last_done(st, start)
        full_day = rule.unit == CoverageRule.Unit.PER_DAY

        for day in _days(start, end):
            if not rule.applies_on(day):
                continue
            slots = [None] if full_day else rule.parts_for()
            for part in slots:
                parts = ["AM", "PM"] if full_day else [part]
                have = min(
                    RotaEntry.objects.filter(
                        day=day, part=p, session_type=st
                    ).count()
                    for p in parts
                )
                for _ in range(max(rule.count - have, 0)):
                    cands = [c for c in clinicians if _eligible(c, day, parts, st)]
                    if not cands:
                        result.unfilled.append(UnfilledSlot(
                            day, part, st.name, "no eligible clinician"))
                        continue
                    if st.fairness_tracked:
                        def sort_key(c):
                            share = total_assigned * weights.get(c.id, 0) / total_weight
                            return (
                                -(share - actuals.get(c.id, 0)),  # biggest deficit first
                                last.get(c.id) or date.min,       # longest-since first
                                c.name,
                            )
                        pick = sorted(cands, key=sort_key)[0]
                        share = total_assigned * weights.get(pick.id, 0) / total_weight
                        reason = f"fair share {share:.1f}, done {actuals.get(pick.id, 0)}"
                    else:
                        pick = min(cands, key=lambda c: (
                            (last.get(c.id) or date.min), c.name))
                        reason = "rotation"
                    n = len(parts)
                    if full_day:
                        entries.assign_full_day(actor, pick, day, st,
                                                manually_set=False, fill_reason=reason)
                    else:
                        entries.assign(actor, pick, day, parts[0], st,
                                       manually_set=False, fill_reason=reason)
                    result.created += n
                    actuals[pick.id] = actuals.get(pick.id, 0) + n
                    total_assigned += n
                    last[pick.id] = day

    if fill_default:
        default = PracticeSettings.load().default_fill_session_type
        if default:
            for day in _days(start, end):
                for part in ["AM", "PM"]:
                    for c in clinicians:
                        if (availability.works_on(c, day, part)
                                and _cell_free(c, day, part)
                                and default.is_eligible(c)):
                            entries.assign(actor, c, day, part, default,
                                           manually_set=False,
                                           fill_reason="default fill")
                            result.created += 1
    return result
