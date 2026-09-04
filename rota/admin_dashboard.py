"""The dashboard: a setup checklist detected from the database, and a
health panel of the things that go quietly wrong. Pure functions over the
ORM; the template renders what they return."""

from datetime import date, timedelta

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from rota.admin_pages import clinicians_without_a_pattern, unmapped_absence_count
from rota.models import (BreatheSyncRun, Clinician, ClinicianGroup, CoverageRule,
                         LocumRequirement, PracticeSettings, SessionType, Site,
                         TraineeProfile)
from rota.services.calendar import is_open
from rota.services.warnings import day_warnings


def _cl(name, **params):
    url = reverse(f"admin:rota_{name}_changelist")
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    return url


def _unlinked():
    return Clinician.objects.filter(active=True, group__is_locum_group=False,
                                    breathe_employee_id=None)


def setup_steps():
    ps = PracticeSettings.load()
    missing_patterns = clinicians_without_a_pattern().count()
    unlinked = _unlinked().count()
    any_active = Clinician.objects.filter(active=True).exists()
    has_key = bool(settings.BREATHE_API_KEY)
    synced = BreatheSyncRun.objects.filter(ok=True).exists()
    if not has_key:
        breathe_detail = "BREATHE_API_KEY is not set"
    elif not synced:
        breathe_detail = "no successful sync yet"
    elif unlinked:
        breathe_detail = f"{unlinked} not linked"
    else:
        breathe_detail = "key set, synced, everyone linked"
    steps = [
        {"title": "Practice settings",
         "done": bool(ps.open_weekday_list()) and ps.default_fill_session_type_id is not None,
         "detail": "open days and a default session type",
         "url": reverse("admin:rota_practicesettings_change", args=[ps.pk])},
        {"title": "Sites", "done": Site.objects.exists(),
         "detail": "at least one", "url": reverse("admin:rota_site_add")},
        {"title": "Clinician groups",
         "done": ClinicianGroup.objects.filter(is_locum_group=True).count() == 1,
         "detail": "at least one, and exactly one locum group",
         "url": _cl("cliniciangroup")},
        # Migration 0022_breathe seeds three ABSENCE-category types (AL/SICK/
        # OTH), so on a real database this step reduces to "has a clinical
        # type" — the absence half is kept so the checklist stays honest if
        # those seeded rows are ever deleted.
        {"title": "Session types",
         "done": SessionType.objects.filter(category=SessionType.Category.CLINICAL).exists()
                 and SessionType.objects.filter(category=SessionType.Category.ABSENCE).exists(),
         "detail": "at least one clinical and one absence type",
         "url": _cl("sessiontype")},
        {"title": "Coverage rules", "done": CoverageRule.objects.exists(),
         "detail": "what must be staffed", "url": _cl("coveragerule")},
        {"title": "Clinicians", "done": any_active,
         "detail": "at least one active", "url": reverse("admin:rota_clinician_add")},
        {"title": "Working patterns",
         "done": any_active and missing_patterns == 0,
         "detail": (f"{missing_patterns} clinician{'s' if missing_patterns != 1 else ''} "
                    f"without one" if missing_patterns else "everyone has one"),
         "url": reverse("admin:rota_patternslot_bulk") + "?missing=1"},
        {"title": "Breathe",
         "done": has_key and synced and unlinked == 0,
         "detail": breathe_detail,
         "url": (_cl("clinician", breathe="unlinked", active__exact=1,
                     group__is_locum_group__exact=0)
                 if has_key and synced
                 else reverse("admin:rota_breathesyncrun_status"))},
    ]
    done = sum(s["done"] for s in steps)
    nxt = next((s for s in steps if not s["done"]), None)
    return {"steps": steps, "done": done, "total": len(steps),
            "next": nxt, "complete": nxt is None}


def health():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    week = [monday + timedelta(days=i) for i in range(7)]
    gap_days = sum(1 for d in week if is_open(d) and day_warnings(d, include_drafts=True))

    last = BreatheSyncRun.objects.first()
    last_ok = BreatheSyncRun.objects.filter(ok=True).first()
    if not settings.BREATHE_API_KEY:
        breathe = ("not configured", "warn")
    elif last is not None and not last.ok:
        breathe = (f"last run failed: {last.error[:80]}", "warn")
    elif last_ok is None:
        breathe = ("no successful sync yet", "warn")
    else:
        local_started = timezone.localtime(last_ok.started)
        breathe = (f"last good sync {local_started:%a %-d %b %H:%M}", "ok")

    ps = PracticeSettings.load()
    trainee_gap = (TraineeProfile.objects.exists()
                   and not (ps.vts_session_type_id and ps.sdl_session_type_id
                            and ps.mentoring_session_type_id))
    return [
        {"label": "Clinicians with no working pattern",
         "count": clinicians_without_a_pattern().count(),
         "url": reverse("admin:rota_patternslot_bulk") + "?missing=1", "level": "warn"},
        {"label": "Clinicians not linked to Breathe", "count": _unlinked().count(),
         "url": _cl("clinician", breathe="unlinked", active__exact=1,
                    group__is_locum_group__exact=0), "level": "warn"},
        {"label": "Breathe sync", "count": None, "detail": breathe[0],
         "url": reverse("admin:rota_breathesyncrun_status"), "level": breathe[1]},
        {"label": "Absences with no mapping", "count": unmapped_absence_count(),
         "url": _cl("breatheleavemapping"), "level": "warn"},
        {"label": "Days with staffing gaps this week", "count": gap_days,
         "url": reverse("report-staffing"), "level": "warn"},
        {"label": "Locum needs not yet advertised (next fortnight)",
         "count": LocumRequirement.objects.filter(
             status__in=[LocumRequirement.Status.POSSIBLE, LocumRequirement.Status.APPROVED],
             day__range=(today, today + timedelta(days=14))).count(),
         "url": _cl("locumrequirement", status__in="POSSIBLE,APPROVED",
                    day__gte=today.isoformat(),
                    day__lte=(today + timedelta(days=14)).isoformat()),
         "level": "warn"},
        {"label": "Trainee session types unset", "count": 1 if trainee_gap else 0,
         "url": reverse("admin:rota_practicesettings_change", args=[ps.pk]), "level": "warn"},
    ]


def dashboard(request, context):
    context["setup"] = setup_steps()
    context["health"] = health()
    return context
