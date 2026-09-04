"""The admin site, and every value settings.UNFOLD reaches by dotted path.

settings.py never imports this module: unfold resolves the dotted strings
in UNFOLD with import_string at request time, which keeps the admin site
out of settings-import order entirely. Nothing here imports a model at
module level, for the same reason.
"""

from django.conf import settings
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.views import redirect_to_login
from django.http import (HttpResponseForbidden, HttpResponseNotAllowed,
                         HttpResponseRedirect)
from django.templatetags.static import static
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from unfold.sites import UnfoldAdminSite


def is_rota_admin(request):
    """The one flag. Superusers are admitted regardless."""
    user = request.user
    return bool(user.is_active and (
        getattr(user, "is_rota_admin", False) or user.is_superuser))


def is_superuser(request):
    return bool(request.user.is_active and request.user.is_superuser)


class RotaAdminSite(UnfoldAdminSite):
    site_title = "Rota"
    site_header = "Practice Rota"
    index_title = "Dashboard"

    def has_permission(self, request):
        return is_rota_admin(request)

    def _safe_next(self, request):
        target = request.GET.get("next", "")
        if target and url_has_allowed_host_and_scheme(
                target, allowed_hosts={request.get_host()},
                require_https=request.is_secure()):
            return target
        return reverse("admin:index")

    @method_decorator(never_cache)
    @login_not_required
    def login(self, request, extra_context=None):
        """One login page — the app's. A signed-in GP gets a 403 rather
        than a loop through a login form that would sign them in again."""
        if request.user.is_authenticated:
            if self.has_permission(request):
                return HttpResponseRedirect(self._safe_next(request))
            return HttpResponseForbidden("This account is not a rota admin.")
        return redirect_to_login(self._safe_next(request), settings.LOGIN_URL)

    def logout(self, request, extra_context=None):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        auth_logout(request)
        return HttpResponseRedirect(settings.LOGOUT_REDIRECT_URL)


# ---- values settings.UNFOLD reaches by dotted path ------------------------

def favicon_32(request):
    return static("icons/favicon-32.png")


def apple_touch_icon(request):
    return static("icons/apple-touch-icon.png")


def style_fonts(request):
    return static("css/fonts.css")


def style_admin(request):
    return static("admin/rota-admin.css")


def script_theme_bridge(request):
    return static("admin/theme-bridge.js")


def settings_link(request):
    """The singleton's own change form — no changelist of one row.

    Deliberately does not call PracticeSettings.load(): the sidebar renders
    on every admin page, including the settings model's own add page, and
    get_or_create() there would silently create the singleton as a side
    effect of a GET request, before an admin has filled in the form —
    exactly the state test_practicesettings_admin_refuses_second_row
    exercises deliberately. Route to the add page until a row exists."""
    from rota.models import PracticeSettings
    obj = PracticeSettings.objects.first()
    if obj is None:
        return reverse("admin:rota_practicesettings_add")
    return reverse("admin:rota_practicesettings_change", args=[obj.pk])


def _item(title, icon, link, permission=is_rota_admin):
    return {"title": title, "icon": icon, "link": link, "permission": permission}


def navigation(request):
    """The sidebar, one group per job. Groups carry no permission of their
    own in unfold's schema, so System is left out of the list entirely
    unless the user is a superuser — an empty heading is worse than none."""
    from django.urls import reverse_lazy as rl
    groups = [
        {"title": "Dashboard", "separator": False, "items": [
            _item("Dashboard", "dashboard", rl("admin:index"))]},
        {"title": "People", "separator": True, "items": [
            _item("Clinicians", "badge", rl("admin:rota_clinician_changelist")),
            _item("Clinician groups", "groups", rl("admin:rota_cliniciangroup_changelist")),
            _item("Login accounts", "manage_accounts", rl("admin:accounts_user_changelist"))]},
        {"title": "Working patterns", "separator": True, "items": [
            _item("Pattern editor", "edit_calendar", rl("admin:rota_patternslot_bulk")),
            _item("Recurring commitments", "event_repeat", rl("admin:rota_recurringcommitment_changelist")),
            _item("Trainee profiles", "school", rl("admin:rota_traineeprofile_changelist"))]},
        {"title": "Calendar", "separator": True, "items": [
            _item("Closed days", "event_busy", rl("admin:rota_closedday_changelist")),
            _item("Day notes", "sticky_note_2", rl("admin:rota_daynote_changelist"))]},
        {"title": "Sessions & rules", "separator": True, "items": [
            _item("Session types", "category", rl("admin:rota_sessiontype_changelist")),
            _item("Coverage rules", "rule", rl("admin:rota_coveragerule_changelist")),
            _item("Trainee stage rules", "menu_book", rl("admin:rota_traineestagerule_changelist")),
            _item("Sites", "location_on", rl("admin:rota_site_changelist"))]},
        {"title": "Leave from Breathe", "separator": True, "items": [
            _item("Sync status", "sync", rl("admin:rota_breathesyncrun_status")),
            _item("Leave mapping", "swap_horiz", rl("admin:rota_breatheleavemapping_changelist")),
            _item("Absences", "sick", rl("admin:rota_breatheabsence_changelist"))]},
        {"title": "Practice settings", "separator": True, "items": [
            _item("Practice settings", "settings", settings_link)]},
        {"title": "Records", "separator": True, "items": [
            _item("Rota entries", "calendar_view_week", rl("admin:rota_rotaentry_changelist")),
            _item("Audit log", "history", rl("admin:rota_rotaentrylog_changelist")),
            _item("Locum requirements", "person_search", rl("admin:rota_locumrequirement_changelist")),
            _item("Swap requests", "swap_calls", rl("admin:rota_swaprequest_changelist"))]},
    ]
    if is_superuser(request):
        groups.append({"title": "System", "separator": True, "items": [
            _item("Auth groups", "shield", rl("admin:auth_group_changelist"), is_superuser),
            _item("Access attempts", "lock", rl("admin:axes_accessattempt_changelist"), is_superuser),
            _item("Access failures", "lock_open", rl("admin:axes_accessfailurelog_changelist"), is_superuser),
            _item("Access logs", "receipt_long", rl("admin:axes_accesslog_changelist"), is_superuser)]})
    return groups
