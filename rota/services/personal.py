"""The clock for personal requirements — the one reader of "last done"
and "due", so the fill pass, the staffing report and the dashboard
cannot disagree.

Due is rolling: N weeks after the clinician's most recent session of the
type, however it got there (fill, hand, import). A clinician with none
yet is due from the requirement's active_from. Once due it stays due
until one is placed; a slip restarts the clock from when it actually
happened, so the aim is "never more than N weeks apart".
"""

from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Max, Prefetch, Q

from rota.models import Clinician, PersonalRequirement, RotaEntry
# Importing fill.accrual initialises the `fill` package, whose `personal`
# pass (rota/services/fill/personal.py) imports this module in turn; that
# is safe because accrual has no dependency on fill/__init__ and the pass
# only reads this module's names at call time — do not add a top-level
# import of fill/__init__ here.
from rota.services.fill.accrual import week_monday


@dataclass(frozen=True)
class Status:
    last: date | None
    due: date            # the Monday of the week it is due
    weeks_overdue: int
    label: str           # "on track" | "due this week" | "<n> week(s) overdue"


def last_done(requirement, clinician_ids, before, *, include_drafts=True):
    """{clinician_id: most recent day of the type strictly before `before`,
    or None}. One query. Drafts count for admins: a planned round is
    still a round; a GP's view passes include_drafts=False."""
    ids = list(clinician_ids)
    qs = RotaEntry.objects.filter(
        session_type_id=requirement.session_type_id,
        clinician_id__in=ids, day__lt=before)
    if not include_drafts:
        qs = qs.filter(is_published=True)
    found = {row["clinician_id"]: row["last"]
             for row in qs.values("clinician_id").annotate(last=Max("day"))}
    return {cid: found.get(cid) for cid in ids}


def due_monday(requirement, last):
    if last is None:
        return week_monday(requirement.active_from)
    return week_monday(last) + timedelta(days=7 * requirement.interval_weeks)


def status_from(requirement, last, today):
    due = due_monday(requirement, last)
    this_week = week_monday(today)
    weeks_overdue = max((this_week - due).days // 7, 0)
    if weeks_overdue:
        label = f"{weeks_overdue} week{'' if weeks_overdue == 1 else 's'} overdue"
    elif due == this_week:
        label = "due this week"
    else:
        label = "on track"
    return Status(last, due, weeks_overdue, label)


def status(requirement, clinician_id, today, *, include_drafts=True):
    last = last_done(requirement, [clinician_id], today + timedelta(days=1),
                     include_drafts=include_drafts)[clinician_id]
    return status_from(requirement, last, today)


def live_requirements(start, end=None):
    """Requirements in force anywhere in `start..end` — active before the
    end, not finished before the start — with their active clinicians in
    grid order. One argument means live on that day. Two queries however
    many there are."""
    end = end or start
    return (PersonalRequirement.objects
            .filter(active_from__lte=end)
            .filter(Q(active_until__isnull=True) | Q(active_until__gte=start))
            .select_related("session_type")
            .prefetch_related(Prefetch(
                "clinicians",
                queryset=Clinician.objects.filter(active=True)
                .order_by("display_order", "name"))))


def overdue_count(today, *, include_drafts=True):
    """(requirement, clinician) pairs overdue today — the Health line."""
    n = 0
    for req in live_requirements(today):
        people = list(req.clinicians.all())
        last = last_done(req, [c.id for c in people], today + timedelta(days=1),
                         include_drafts=include_drafts)
        n += sum(1 for c in people
                 if status_from(req, last[c.id], today).weeks_overdue > 0)
    return n
