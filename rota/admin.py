from django.contrib import admin

from .models import Clinician, ClinicianGroup, SessionType, Site


@admin.register(ClinicianGroup)
class ClinicianGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "display_order", "min_per_session", "is_locum_group")


@admin.register(Clinician)
class ClinicianAdmin(admin.ModelAdmin):
    list_display = ("name", "initials", "group", "active", "leave_entitlement_sessions")
    list_filter = ("group", "active")


@admin.register(SessionType)
class SessionTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "category", "fairness_tracked",
                    "counts_toward_entitlement")
    filter_horizontal = ("allowed_clinicians", "allowed_groups")


admin.site.register(Site)
