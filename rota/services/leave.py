from calendar import monthrange
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from rota.models import LeaveRequest, PracticeSettings, RotaEntry
from rota.services import availability, calendar, entries


def sessions_affected(req):
    out = []
    d = req.start_date
    while d <= req.end_date:
        if calendar.is_open(d):
            for part in ["AM", "PM"]:
                if availability.works_on(req.clinician, d, part):
                    out.append((d, part))
        d += timedelta(days=1)
    return out


def entries_overwritten(req, slots=None):
    if slots is None:
        slots = sessions_affected(req)
    return [
        e for e in RotaEntry.objects.filter(
            clinician=req.clinician,
            day__range=(req.start_date, req.end_date),
        ).select_related("session_type")
        if (e.day, e.part) in slots
    ]


@transaction.atomic
def approve(actor, req, comment=""):
    for day, part in sessions_affected(req):
        entries.assign(actor, req.clinician, day, part, req.session_type,
                       published=True, manually_set=True)
    req.status = LeaveRequest.Status.APPROVED
    req.admin_comment = comment
    req.decided_by = actor
    req.decided_at = timezone.now()
    req.save()


def decline(actor, req, comment=""):
    req.status = LeaveRequest.Status.DECLINED
    req.admin_comment = comment
    req.decided_by = actor
    req.decided_at = timezone.now()
    req.save()


def _clamped_date(year, month, day):
    """date(year, month, day), clamped to the last valid day of that month
    if the literal day doesn't exist in that year (29 Feb in a non-leap
    year). An admin who configures 29 Feb means "end of February", so
    clamping is preferred over rejecting the configuration."""
    last_day = monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def leave_year_bounds(today):
    s = PracticeSettings.load()
    month, day = s.leave_year_start_month, s.leave_year_start_day
    start = _clamped_date(today.year, month, day)
    if start > today:
        start = _clamped_date(today.year - 1, month, day)
    end = _clamped_date(start.year + 1, month, day) - timedelta(days=1)
    return start, end


def leave_summary(clinician, today):
    start, end = leave_year_bounds(today)
    qs = RotaEntry.objects.filter(
        clinician=clinician, is_published=True, day__range=(start, end),
        session_type__counts_toward_entitlement=True,
    )
    taken = qs.filter(day__lt=today).count()
    booked = qs.filter(day__gte=today).count()
    entitlement = clinician.leave_entitlement_sessions
    return {"entitlement": entitlement, "taken": taken, "booked": booked,
            "remaining": entitlement - taken - booked}
