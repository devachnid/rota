"""The dashboard: a setup checklist detected from the database, and a
health panel of the things that go quietly wrong. Pure functions over the
ORM; the template renders what they return."""

from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone

from accounts.mail import email_is_configured
from feedback.models import Feedback
from rota.admin_pages import clinicians_without_a_pattern, unmapped_count
from rota.models import (TimeOffSyncRun, Clinician, ClinicianGroup, CoverageRule,
                         LocumRequirement, PracticeSettings, SessionType, Site,
                         TraineeProfile, SwapRequest)
from rota.services import personal as personal_svc
from rota.services.shift_central import client as sc_client, sync as sc_sync
from rota.services.shift_central.links import without_email, without_email_changelist_url
from rota.services.calendar import is_open
from rota.services.legibility import grid_legibility
from rota.services.warnings import day_warnings


def _cl(name, **params):
    url = reverse(f"admin:rota_{name}_changelist")
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    return url


def setup_steps():
    ps = PracticeSettings.load()
    missing_patterns = clinicians_without_a_pattern().count()
    no_email = without_email().count()
    unmatched = len(sc_sync.unmatched_emails())
    any_active = Clinician.objects.filter(active=True).exists()
    has_token = sc_client.from_settings() is not None
    synced = TimeOffSyncRun.objects.filter(ok=True).exists()
    email_ok = email_is_configured()
    if not has_token:
        sc_detail = "SHIFT_CENTRAL_URL or SHIFT_CENTRAL_TOKEN is not set"
    elif not synced:
        sc_detail = "no successful sync yet"
    elif no_email:
        sc_detail = f"{no_email} without a login email"
    elif unmatched:
        sc_detail = f"{unmatched} email{'s' if unmatched != 1 else ''} unmatched"
    else:
        sc_detail = "token set, synced, everyone matched"
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
        # Migrations 0022 and 0034 seed three ABSENCE-category types (AL/SICK/
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
        {"title": "Shift Central",
         "done": has_token and synced and unmatched == 0 and no_email == 0,
         "detail": sc_detail,
         "url": (without_email_changelist_url() if has_token and synced and no_email
                 else reverse("admin:rota_timeoffsyncrun_status"))},
        # Server configuration, not a database row, so nothing to link to.
        {"title": "Outgoing email", "done": email_ok,
         "detail": ("invitations and password resets go by email" if email_ok
                    else "EMAIL_HOST is not set — invitations show as links to copy"),
         "url": None},
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

    last = TimeOffSyncRun.objects.first()
    last_ok = TimeOffSyncRun.objects.filter(ok=True).first()
    if sc_client.from_settings() is None:
        shift_central = ("not configured", "warn")
    elif last is not None and not last.ok:
        shift_central = (f"last run failed: {last.error[:80]}", "warn")
    elif last_ok is None:
        shift_central = ("no successful sync yet", "warn")
    else:
        local_started = timezone.localtime(last_ok.started)
        shift_central = (f"last good sync {local_started:%a %-d %b %H:%M}", "ok")

    ps = PracticeSettings.load()
    legibility = grid_legibility()
    trainee_gap = (TraineeProfile.objects.exists()
                   and not (ps.vts_session_type_id and ps.sdl_session_type_id
                            and ps.mentoring_session_type_id))
    return [
        {"label": "Clinicians with no working pattern",
         "count": clinicians_without_a_pattern().count(),
         "url": reverse("admin:rota_patternslot_bulk") + "?missing=1", "level": "warn"},
        {"label": "Clinicians without a login email",
         "count": without_email().count(),
         "url": without_email_changelist_url(), "level": "warn"},
        {"label": "Shift Central sync", "count": None, "detail": shift_central[0],
         "url": reverse("admin:rota_timeoffsyncrun_status"), "level": shift_central[1]},
        {"label": "Time off reasons with no mapping", "count": unmapped_count(),
         "url": _cl("timeoffmapping"), "level": "warn"},
        {"label": "Days with staffing gaps this week", "count": gap_days,
         "url": reverse("report-staffing"), "level": "warn"},
        {"label": "Clinicians overdue a personal requirement",
         "count": personal_svc.overdue_count(today, include_drafts=True),
         "url": reverse("report-staffing") + "#personal", "level": "warn"},
        {"label": "Locum needs not yet advertised (next fortnight)",
         "count": LocumRequirement.objects.filter(
             status__in=[LocumRequirement.Status.POSSIBLE, LocumRequirement.Status.APPROVED],
             day__range=(today, today + timedelta(days=14))).count(),
         "url": _cl("locumrequirement", status__in="POSSIBLE,APPROVED",
                    day__gte=today.isoformat(),
                    day__lte=(today + timedelta(days=14)).isoformat()),
         "level": "warn"},
        # Both read one pass over the session types (rota/services/
        # legibility.py) — a type configured so the grid cannot show it
        # looks perfectly fine on its own admin page.
        {"label": "Session types sharing a colour",
         "count": legibility.sharing_count,
         "url": _cl("sessiontype"), "level": "warn"},
        {"label": "Session codes too long for the grid",
         "count": len(legibility.clipped),
         "url": _cl("sessiontype"), "level": "warn"},
        {"label": "Trainee session types unset", "count": 1 if trainee_gap else 0,
         "url": reverse("admin:rota_practicesettings_change", args=[ps.pk]), "level": "warn"},
        {"label": "Swaps awaiting your approval",
         "count": SwapRequest.objects.filter(status=SwapRequest.Status.ACCEPTED).count(),
         "url": reverse("inbox"), "level": "warn"},
        {"label": "Feedback not yet looked at",
         "count": Feedback.objects.filter(status=Feedback.Status.NEW).count(),
         "url": reverse("admin:feedback_feedback_changelist") + "?status__exact=NEW",
         "level": "warn"},
    ]


def dashboard(request, context):
    context["setup"] = setup_steps()
    context["health"] = health()
    return context
