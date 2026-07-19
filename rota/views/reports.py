from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rota.models import Clinician, RotaEntry, SessionType
from rota.services import fairness as fairness_svc
from rota.services import leave as leave_svc
from rota.services.calendar import is_open
from rota.services.warnings import day_warnings


def _range(request, days_back=91):
    today = date.today()
    try:
        start = date.fromisoformat(request.GET.get("start", ""))
    except ValueError:
        start = today - timedelta(days=days_back)
    try:
        end = date.fromisoformat(request.GET.get("end", ""))
    except ValueError:
        end = today
    return start, end


@login_required
def report_fairness(request):
    start, end = _range(request)
    clinicians = {c.id: c for c in Clinician.objects.filter(active=True)}
    tables = []
    for st in SessionType.objects.filter(fairness_tracked=True):
        shares = fairness_svc.fair_shares(
            st, start, end, include_drafts=request.user.is_rota_admin)
        rows = [
            {"clinician": clinicians[cid], "share": fs.share,
             "actual": fs.actual, "balance": fs.balance}
            for cid, fs in sorted(shares.items(),
                                  key=lambda kv: kv[1].balance)
            if cid in clinicians
        ]
        tables.append({"session_type": st, "rows": rows})
    return render(request, "rota/report_fairness.html",
                  {"tables": tables, "start": start, "end": end})


@login_required
def report_leave(request):
    today = date.today()
    rows = [
        {"clinician": c, **leave_svc.leave_summary(c, today)}
        for c in Clinician.objects.filter(active=True)
    ]
    upcoming = RotaEntry.objects.filter(
        is_published=True, session_type__category="ABSENCE",
        day__range=(today, today + timedelta(weeks=8)),
    ).select_related("clinician", "session_type")
    return render(request, "rota/report_leave.html",
                  {"rows": rows, "upcoming": upcoming})


@login_required
def report_staffing(request):
    try:
        weeks = int(request.GET.get("weeks", 8))
    except ValueError:
        weeks = 8
    weeks = max(1, min(weeks, 26))
    today = date.today()
    include_drafts = request.user.is_rota_admin
    days = []
    for i in range(weeks * 7):
        d = today + timedelta(days=i)
        if not is_open(d):
            continue
        warnings = day_warnings(d, include_drafts=include_drafts)
        if warnings:
            days.append({"day": d, "warnings": warnings})
    return render(request, "rota/report_staffing.html",
                  {"days": days, "weeks": weeks})
