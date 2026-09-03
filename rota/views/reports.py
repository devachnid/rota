from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from rota.models import (BreatheAbsence, BreatheLeaveMapping, Clinician,
                         CoverageRule, LocumRequirement, PatternSlot,
                         PracticeSettings, RotaEntry, SessionType,
                         TraineeProfile, TraineeStageRule)
from rota.services import fairness as fairness_svc
from rota.services.availability import AvailabilityResolver
from rota.services.calendar import is_open
from rota.services.cells import cell_state
from rota.services.fill.accrual import (due_through, epoch_for, week_monday,
                                        weekly_rate)
from rota.services.fill.trainees import _anchor as trainee_anchor
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
        ]
        tables.append({"session_type": st, "rows": rows})
    return render(request, "rota/report_fairness.html",
                  {"tables": tables, "start": start, "end": end})


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
        if not request.user.is_rota_admin:
            warnings = [w for w in warnings if w.code != "breathe"]
        if warnings:
            days.append({"day": d, "warnings": warnings})
    return render(request, "rota/report_staffing.html",
                  {"days": days, "weeks": weeks,
                   "accrual_rows": _accrual_targets(today, include_drafts=include_drafts)})


def _accrual_targets(today, include_drafts=True):
    """Trailing-4-whole-weeks accrual check for demand-driven CoverageRules.

    Measures only completed weeks: the current, in-flight week is excluded
    from both sides so a rule doesn't read "behind target" purely because
    today is early in the week and this week's session hasn't happened yet.
    """
    epoch = epoch_for(today)
    wm_now = week_monday(today)
    wm_this_week_start = wm_now - timedelta(days=7)
    wm_prev = wm_now - timedelta(days=35)
    rows = []
    rules = CoverageRule.objects.filter(
        frequency__in=[CoverageRule.Frequency.PER_WEEK,
                       CoverageRule.Frequency.PER_MONTH],
    ).select_related("session_type")
    for rule in rules:
        rate = weekly_rate(rule)
        expected = (due_through(rate, epoch, wm_this_week_start)
                    - due_through(rate, epoch, wm_prev))
        # `expected` covers the four completed weeks starting wm_now-28 ..
        # wm_now-7, i.e. the calendar span [wm_now-28, wm_now-1]; `actual`
        # must match that same span exactly.
        actual = sum(fairness_svc.counts(
            rule.session_type, wm_now - timedelta(days=28), wm_now - timedelta(days=1),
            include_drafts=include_drafts,
        ).values())
        behind = expected - actual
        if behind > 0:
            rows.append({"name": rule.session_type.name, "behind": behind})
    return rows


_TRAINEE_REQUIREMENTS = (("vts", "VTS"), ("sdl", "SDL"), ("mentoring", "Mentoring"))


@login_required
def report_trainees(request):
    today = date.today()
    settings = PracticeSettings.load()
    type_for = {
        "vts": settings.vts_session_type,
        "sdl": settings.sdl_session_type,
        "mentoring": settings.mentoring_session_type,
    }
    configured_type_ids = [st.id for st in type_for.values() if st]

    include_drafts = request.user.is_rota_admin

    profiles = list(
        TraineeProfile.objects.filter(
            clinician__active=True, placement_start__lte=today,
            placement_end__gte=today,
        ).select_related("clinician").order_by("clinician__name")
    )

    # weekly_rates() looks up the stage rule, which otherwise costs one query
    # per trainee. There are only four stages, so fetch them once and hand the
    # mapping down.
    stage_rules = {r.stage: r for r in TraineeStageRule.objects.all()}

    # One query for every delivered entry across all trainees/types, bucketed
    # in Python by (clinician, session_type) to avoid N+1 across the table.
    delivered_days = {}
    if profiles and configured_type_ids:
        clinician_ids = [p.clinician_id for p in profiles]
        entries_qs = RotaEntry.objects.filter(
            clinician_id__in=clinician_ids, session_type_id__in=configured_type_ids,
        )
        if not include_drafts:
            entries_qs = entries_qs.filter(is_published=True)
        for row in entries_qs.values("clinician_id", "session_type_id", "day"):
            key = (row["clinician_id"], row["session_type_id"])
            delivered_days.setdefault(key, []).append(row["day"])

    rows = []
    for profile in profiles:
        rates = profile.weekly_rates(stage_rules)
        anchor = trainee_anchor(profile)
        as_of = min(today, profile.placement_end)
        wm = week_monday(as_of)
        reqs = []
        for key, label in _TRAINEE_REQUIREMENTS:
            st = type_for[key]
            if st is None:
                reqs.append({"label": label, "configured": False})
                continue
            rate, _weekday, _part = rates[key]
            expected = due_through(rate, anchor, wm)
            days = delivered_days.get((profile.clinician_id, st.id), [])
            delivered = sum(1 for d in days if anchor <= d <= as_of)
            reqs.append({
                "label": label, "configured": True,
                "expected": expected, "delivered": delivered,
                "diff": delivered - expected,
            })
        rows.append({"profile": profile, "reqs": reqs})

    return render(request, "rota/report_trainees.html", {"rows": rows})


def _locum_absence_label(cell):
    """What the covered clinician was off for, in the report's words.

    Breathe first (the label never goes through the mapping), then an
    absence-category entry standing on the cell (a hand-placed AL, or
    history from before the overlay), then nothing we know about.
    """
    if cell["on_leave"]:
        return cell["leave_label"]
    entry = cell["entry"]
    if entry is not None and entry.session_type.category == SessionType.Category.ABSENCE:
        return entry.session_type.name
    return "No absence recorded"


def _locum_rows(bookings, start, end, include_drafts):
    """One row per booking, with the covered clinician's absence decided by
    cell_state so this report can never disagree with the grid. One
    resolver and one entry fetch for all rows — no per-row queries."""
    covered = {b.covering_id: b.covering for b in bookings if b.covering_id}
    entries = RotaEntry.objects.filter(
        clinician_id__in=covered, day__range=(start, end)
    ).select_related("session_type")
    if not include_drafts:
        entries = entries.filter(is_published=True)
    entry_at = {(e.clinician_id, e.day, e.part): e for e in entries}
    resolver = AvailabilityResolver(
        PatternSlot.objects.filter(clinician_id__in=covered),
        covered.values(),
        BreatheAbsence.objects.filter(clinician_id__in=covered,
                                      start_date__lte=end, end_date__gte=start),
        BreatheLeaveMapping.as_dict(),
    )
    rows = []
    for b in bookings:
        if b.covering_id:
            cell = cell_state(b.covering_id, b.day, b.part,
                              entry=entry_at.get((b.covering_id, b.day, b.part)),
                              resolver=resolver, closed=False)
            absence = _locum_absence_label(cell)
        else:
            absence = "—"
        rows.append({"booking": b, "absence": absence,
                     "cleared": b.rota_entry_id is None})
    return rows


@login_required
def report_locums(request):
    start, end = _range(request, days_back=30)
    bookings = list(
        LocumRequirement.objects.filter(
            status=LocumRequirement.Status.BOOKED, day__range=(start, end)
        ).select_related("clinician", "covering", "session_type")
        .order_by("day", "part", "clinician__name")
    )
    rows = _locum_rows(bookings, start, end,
                       include_drafts=request.user.is_rota_admin)
    absence_options = sorted({r["absence"] for r in rows})

    locum_id = request.GET.get("locum") or None
    covering_id = request.GET.get("covering") or None
    absence = request.GET.get("absence") or None
    if locum_id:
        rows = [r for r in rows if str(r["booking"].clinician_id) == locum_id]
    if covering_id:
        rows = [r for r in rows if str(r["booking"].covering_id) == covering_id]
    if absence:
        rows = [r for r in rows if r["absence"] == absence]

    return render(request, "rota/report_locums.html", {
        "rows": rows, "start": start, "end": end,
        "locums": Clinician.objects.filter(group__is_locum_group=True).order_by("name"),
        "coverable": Clinician.objects.filter(
            pk__in=LocumRequirement.objects.filter(
                status=LocumRequirement.Status.BOOKED, covering__isnull=False
            ).values("covering")).order_by("name"),
        "absence_options": absence_options,
        "locum_id": locum_id, "covering_id": covering_id, "absence": absence,
    })
