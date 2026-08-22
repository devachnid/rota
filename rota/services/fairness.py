from dataclasses import dataclass

from django.db.models import Count, Max

from rota.models import Clinician, RotaEntry
from rota.services import availability


@dataclass
class FairShare:
    actual: int
    share: float

    @property
    def balance(self):
        return self.actual - self.share


def counts(session_type, start, end, include_drafts=True):
    qs = RotaEntry.objects.filter(
        session_type=session_type, day__range=(start, end)
    )
    if not include_drafts:
        qs = qs.filter(is_published=True)
    return {
        row["clinician"]: row["n"]
        for row in qs.values("clinician").annotate(n=Count("id"))
    }


def weights(as_of):
    return {
        c.id: availability.weekly_sessions(c, as_of)
        for c in Clinician.objects.filter(active=True)
    }


def fair_shares(session_type, start, end, include_drafts=True):
    actuals = counts(session_type, start, end, include_drafts)
    pool = [c for c in Clinician.objects.filter(active=True)
            if session_type.is_eligible(c)]
    w = {c.id: availability.weekly_sessions(c, end) for c in pool}
    total_weight = sum(w.values())
    total_assigned = sum(actuals.values())
    result = {}
    for cid, weight in w.items():
        share = total_assigned * weight / total_weight if total_weight else 0.0
        result[cid] = FairShare(actual=actuals.get(cid, 0), share=share)
    return result


def last_done(session_type, before):
    qs = (
        RotaEntry.objects.filter(session_type=session_type, day__lt=before)
        .values("clinician")
        .annotate(last=Max("day"))
    )
    return {row["clinician"]: row["last"] for row in qs}
