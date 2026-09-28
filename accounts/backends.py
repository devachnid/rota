"""is_rota_admin is the one flag.

Django's admin asks `user.has_perm("rota.change_clinician")` for every page
and every save. A practice manager should never have to be granted those
one by one, so this backend answers yes to every permission on the apps
the rota owns — and to nothing else, which keeps django-axes and auth
Groups for superusers. It authenticates nobody (BaseBackend.authenticate
returns None); axes and ModelBackend do that.
"""

from django.contrib.auth.backends import BaseBackend

ROTA_APPS = {"rota", "accounts", "feedback"}


def _is_rota_admin(user):
    return bool(user.is_active and getattr(user, "is_rota_admin", False))


class RotaAdminBackend(BaseBackend):
    def has_perm(self, user_obj, perm, obj=None):
        return (_is_rota_admin(user_obj) and "." in perm
                and perm.split(".", 1)[0] in ROTA_APPS)

    def has_module_perms(self, user_obj, app_label):
        return _is_rota_admin(user_obj) and app_label in ROTA_APPS


class SuperuserPasswordOnly:
    """With the practice account configured (PRACTICE_HR_URL), the rota's
    own password form is for the superuser only: everyone else signs in
    through the HR system, which is where their password, lockout and
    leaving date live. The superuser has no HR record and never will, and
    this form is also the way in if the HR system is unreachable.

    Listed before ModelBackend. For a password sign-in by anyone but a
    superuser it raises PermissionDenied, which stops authenticate() at
    once — ModelBackend never checks the password — and sends
    user_login_failed, so axes counts it like a wrong password. The
    superuser falls through to ModelBackend. Anything without a password
    (the practice-account backend) is not its business. Without
    PRACTICE_HR_URL it does nothing at all.

    Not a BaseBackend on purpose: it has no get_user(), so it is never
    the backend a session is attached to — force_login() and login()
    pick the first backend that has one."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        from django.conf import settings
        from django.core.exceptions import PermissionDenied

        from .models import User

        if not settings.PRACTICE_HR_URL or password is None:
            return None
        user = User.objects.filter(email__iexact=username or "").first()
        if user is not None and user.is_superuser:
            return None
        raise PermissionDenied
