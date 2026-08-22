from datetime import date, timedelta

from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from .models import (Clinician, ClinicianGroup, ClosedDay, CoverageRule,
                     DayNote, LeaveRequest, LocumRequirement, Part,
                     PatternSlot, PracticeSettings, RotaEntry, RotaEntryLog,
                     SessionType, Site, SwapRequest, TraineeProfile, TraineeStageRule)
from .services.patterns import bulk_set_pattern, current_pattern

WEEKDAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                  "Saturday", "Sunday"]


@admin.register(ClinicianGroup)
class ClinicianGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "display_order", "min_per_session", "is_locum_group")


class TraineeProfileInline(admin.StackedInline):
    model = TraineeProfile
    fk_name = "clinician"
    extra = 0


@admin.register(Clinician)
class ClinicianAdmin(admin.ModelAdmin):
    list_display = ("name", "initials", "group", "active", "is_trainer",
                    "leave_entitlement_sessions", "pattern_link")
    list_filter = ("group", "active")
    inlines = [TraineeProfileInline]

    def pattern_link(self, obj):
        url = reverse("admin:rota_patternslot_bulk")
        return format_html(
            '<a href="{}?clinician_id={}">Edit pattern</a>', url, obj.pk
        )
    pattern_link.short_description = "Pattern"


@admin.register(SessionType)
class SessionTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "category", "fairness_tracked",
                    "counts_toward_entitlement")
    filter_horizontal = ("allowed_clinicians", "allowed_groups", "blocks_same_day")


admin.site.register(Site)


@admin.register(PatternSlot)
class PatternSlotAdmin(admin.ModelAdmin):
    list_display = ("clinician", "weekday", "part", "works", "effective_from")
    list_filter = ("clinician",)
    change_list_template = "admin/rota/patternslot/change_list.html"

    def get_urls(self):
        return [
            path("bulk/", self.admin_site.admin_view(self.bulk_view),
                 name="rota_patternslot_bulk"),
        ] + super().get_urls()

    def bulk_view(self, request):
        clinicians = Clinician.objects.filter(active=True).order_by("name")
        clinician = None
        clinician_id = (request.POST.get("clinician_id")
                        or request.GET.get("clinician_id"))
        if clinician_id:
            clinician = get_object_or_404(Clinician, pk=clinician_id)

        try:
            effective_from = date.fromisoformat(
                request.POST.get("effective_from")
                or request.GET.get("effective_from") or ""
            )
        except ValueError:
            effective_from = date.today()

        if request.method == "POST" and clinician:
            desired = {
                (weekday, part): f"d{weekday}_{part}" in request.POST
                for weekday in range(7)
                for part in Part.values
            }
            changed = bulk_set_pattern(clinician, effective_from, desired)
            messages.success(
                request,
                f"Saved pattern for {clinician.name} effective "
                f"{effective_from} ({changed} slot(s) changed).",
            )
            return redirect(
                f"{request.path}?clinician_id={clinician.pk}"
                f"&effective_from={effective_from.isoformat()}"
            )

        grid = None
        if clinician:
            prior = current_pattern(clinician, effective_from - timedelta(days=1))
            grid = [
                {
                    "weekday": weekday,
                    "label": WEEKDAY_LABELS[weekday],
                    "am_checked": prior.get((weekday, "AM"), False),
                    "pm_checked": prior.get((weekday, "PM"), False),
                }
                for weekday in range(7)
            ]

        context = {
            **self.admin_site.each_context(request),
            "title": "Bulk edit clinician pattern",
            "opts": self.model._meta,
            "clinicians": clinicians,
            "clinician": clinician,
            "effective_from": effective_from,
            "grid": grid,
        }
        return render(request, "admin/rota/patternslot/bulk_form.html", context)


@admin.register(CoverageRule)
class CoverageRuleAdmin(admin.ModelAdmin):
    list_display = ("session_type", "unit", "frequency", "parts", "weekdays",
                    "months", "count", "priority")


@admin.register(TraineeStageRule)
class TraineeStageRuleAdmin(admin.ModelAdmin):
    list_display = ("stage", "vts_per_week", "sdl_per_week",
                    "mentoring_per_week", "vts_weekday", "vts_part")


admin.site.register(ClosedDay)
admin.site.register(DayNote)
admin.site.register(PracticeSettings)


@admin.register(RotaEntry)
class RotaEntryAdmin(admin.ModelAdmin):
    list_display = ("day", "part", "clinician", "session_type", "is_published",
                    "manually_set")
    list_filter = ("is_published", "session_type")


@admin.register(RotaEntryLog)
class RotaEntryLogAdmin(admin.ModelAdmin):
    list_display = ("at", "actor", "action", "day", "part", "clinician_name", "detail")
    readonly_fields = [f.name for f in RotaEntryLog._meta.fields]


@admin.register(LocumRequirement)
class LocumRequirementAdmin(admin.ModelAdmin):
    list_display = ("day", "part", "session_type", "status", "clinician")
    list_filter = ("status",)


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ("clinician", "session_type", "start_date", "end_date", "status")
    list_filter = ("status",)


@admin.register(SwapRequest)
class SwapRequestAdmin(admin.ModelAdmin):
    list_display = ("proposer", "colleague", "status", "created_at")
    list_filter = ("status",)
