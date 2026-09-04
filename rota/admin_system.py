"""The superuser-only tables, re-registered on unfold's ModelAdmin so even
the System group does not look like stock Django. django-axes and auth
register their own admins first (INSTALLED_APPS order), so this
unregisters and re-registers; the list columns and filters are theirs."""

from axes.admin import (AccessAttemptAdmin as AxesAttempt,
                        AccessFailureLogAdmin as AxesFailure,
                        AccessLogAdmin as AxesLog)
from axes.models import AccessAttempt, AccessFailureLog, AccessLog
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import Group
from unfold.admin import ModelAdmin

for model in (AccessAttempt, AccessFailureLog, AccessLog, Group):
    if admin.site.is_registered(model):
        admin.site.unregister(model)


@admin.register(AccessAttempt)
class AccessAttemptAdmin(AxesAttempt, ModelAdmin):
    pass


@admin.register(AccessFailureLog)
class AccessFailureLogAdmin(AxesFailure, ModelAdmin):
    pass


@admin.register(AccessLog)
class AccessLogAdmin(AxesLog, ModelAdmin):
    pass


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass
