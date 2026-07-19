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


from .models import ClosedDay, CoverageRule, DayNote, PatternSlot, PracticeSettings  # noqa: E402


@admin.register(PatternSlot)
class PatternSlotAdmin(admin.ModelAdmin):
    list_display = ("clinician", "weekday", "part", "works", "effective_from")
    list_filter = ("clinician",)


@admin.register(CoverageRule)
class CoverageRuleAdmin(admin.ModelAdmin):
    list_display = ("session_type", "unit", "parts", "weekdays", "count", "priority")


admin.site.register(ClosedDay)
admin.site.register(DayNote)
admin.site.register(PracticeSettings)


from .models import RotaEntry, RotaEntryLog  # noqa: E402


@admin.register(RotaEntry)
class RotaEntryAdmin(admin.ModelAdmin):
    list_display = ("day", "part", "clinician", "session_type", "is_published",
                    "manually_set")
    list_filter = ("is_published", "session_type")


@admin.register(RotaEntryLog)
class RotaEntryLogAdmin(admin.ModelAdmin):
    list_display = ("at", "actor", "action", "day", "part", "clinician_name", "detail")
    readonly_fields = [f.name for f in RotaEntryLog._meta.fields]


from .models import LocumRequirement  # noqa: E402


@admin.register(LocumRequirement)
class LocumRequirementAdmin(admin.ModelAdmin):
    list_display = ("day", "part", "session_type", "status", "clinician")
    list_filter = ("status",)
