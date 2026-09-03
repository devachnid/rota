"""is_rota_admin is the one flag.

Django's admin asks `user.has_perm("rota.change_clinician")` for every page
and every save. A practice manager should never have to be granted those
one by one, so this backend answers yes to every permission on the two apps
the rota owns — and to nothing else, which keeps django-axes and auth
Groups for superusers. It authenticates nobody (BaseBackend.authenticate
returns None); axes and ModelBackend do that.
"""

from django.contrib.auth.backends import BaseBackend

ROTA_APPS = {"rota", "accounts"}


def _is_rota_admin(user):
    return bool(user.is_active and getattr(user, "is_rota_admin", False))


class RotaAdminBackend(BaseBackend):
    def has_perm(self, user_obj, perm, obj=None):
        return _is_rota_admin(user_obj) and perm.split(".", 1)[0] in ROTA_APPS

    def has_module_perms(self, user_obj, app_label):
        return _is_rota_admin(user_obj) and app_label in ROTA_APPS
