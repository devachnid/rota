"""The admin site, and every value settings.UNFOLD reaches by dotted path.

settings.py never imports this module: unfold resolves the dotted strings
in UNFOLD with import_string at request time, which keeps the admin site
out of settings-import order entirely. Nothing here imports a model at
module level, for the same reason.
"""

from django.conf import settings
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.views import redirect_to_login
from django.http import (HttpResponseForbidden, HttpResponseNotAllowed,
                         HttpResponseRedirect)
from django.templatetags.static import static
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
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


def navigation(request):
    """The sidebar. Filled in by the sidebar task."""
    return []
