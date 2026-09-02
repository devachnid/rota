from datetime import date

from django.contrib import admin, messages
from django.contrib.admin.utils import NestedObjects
from django.db import router
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, path, reverse
from django.utils.html import format_html
from django.utils.text import capfirst

from .models import (Clinician, ClinicianGroup, ClosedDay, CoverageRule,
                     DayNote, LocumRequirement, Part,
                     PatternSlot, PracticeSettings, RecurringCommitment, RotaEntry, RotaEntryLog,
                     SessionType, Site, SwapRequest, TraineeProfile, TraineeStageRule)
from .services.patterns import bulk_set_pattern, current_pattern
from .admin_widgets import TintSwatchSelect

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
                    "start_date", "end_date",
                    "pattern_link")
    list_filter = ("group", "active")
    inlines = [TraineeProfileInline]
    actions = ["deactivate_clinicians"]

    @admin.action(description="Deactivate selected clinicians")
    def deactivate_clinicians(self, request, queryset):
        n = queryset.update(active=False)
        self.message_user(
            request,
            f"Deactivated {n} clinician(s). Their history is intact and they "
            f"no longer appear in any eligibility pool.")

    def get_deleted_objects(self, objs, request):
        """RotaEntry.clinician is PROTECT, and that fires while rendering the
        confirmation page — before any delete code runs. So the split between
        "deletable drafts" and "protected published entries" has to happen
        here, not in delete_model.
        """
        deletable, model_count, perms_needed, protected = \
            super().get_deleted_objects(objs, request)

        published = RotaEntry.objects.filter(
            clinician__in=objs, is_published=True)
        n_published = published.count()

        if n_published:
            protected = list(protected) + [
                f"{n_published} published rota entr"
                f"{'y' if n_published == 1 else 'ies'} — deletion would destroy "
                f"rota history. Deactivate this clinician instead: it keeps "
                f"their record and history, and removes them from every "
                f"eligibility pool."
            ]
            return deletable, model_count, perms_needed, protected

        # No published entries. Django's collector still protects every
        # RotaEntry tied to these clinicians — PROTECT raises for the whole
        # batch on that field, so it cannot distinguish a draft from a
        # published row. delete_model()/delete_queryset() remove the drafts
        # before the real delete runs, so those specific rows are not
        # actually a problem. But RotaEntry.clinician being the only PROTECT
        # relation on Clinician is a fact about today's schema, not something
        # this method enforces — so rather than trust that and blank the
        # whole list, re-run the collector ourselves, remove by identity only
        # the drafts we are about to delete, and re-format whatever (if
        # anything) is still protected. If a future PROTECT relation ever
        # lands something else in there, it stays protected here too.
        drafts = set(RotaEntry.objects.filter(
            clinician__in=objs, is_published=False))

        collector = NestedObjects(using=router.db_for_write(self.model))
        collector.collect(objs)
        still_protected = collector.protected - drafts
        protected = [self._format_protected(obj, request)
                     for obj in still_protected]

        n_drafts = len(drafts)
        if n_drafts:
            deletable = list(deletable) + [
                f"{n_drafts} unpublished rota entr"
                f"{'y' if n_drafts == 1 else 'ies'} (will be deleted)"
            ]
        # Everything else cascades: pattern slots, leave requests, recurring
        # commitments, the trainee profile, and swap requests — including ones
        # where this clinician was the *colleague*, which touches someone
        # else's history. Locum bookings survive with the name set to null.
        # The audit log is unaffected: it stores names as text, not a key.
        return deletable, model_count, perms_needed, protected

    def _format_protected(self, obj, request):
        """Render a still-protected object the same way
        django.contrib.admin.utils.get_deleted_objects does — a verbose
        name, and a link to the change view where one exists — so an object
        that survives the drafts filter above (something other than this
        clinician's own unpublished RotaEntry rows) still reads the way
        Django's own confirmation page would have shown it.
        """
        opts = obj._meta
        no_edit_link = f"{capfirst(opts.verbose_name)}: {obj}"
        if not self.admin_site.is_registered(obj.__class__):
            return no_edit_link
        try:
            admin_url = reverse(
                f"{self.admin_site.name}:{opts.app_label}_{opts.model_name}_change",
                None, (obj.pk,))
        except NoReverseMatch:
            return no_edit_link
        return format_html(
            '{}: <a href="{}">{}</a>', capfirst(opts.verbose_name), admin_url, obj)

    def delete_model(self, request, obj):
        RotaEntry.objects.filter(clinician=obj, is_published=False).delete()
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        RotaEntry.objects.filter(
            clinician__in=queryset, is_published=False).delete()
        super().delete_queryset(request, queryset)

    def pattern_link(self, obj):
        url = reverse("admin:rota_patternslot_bulk")
        return format_html(
            '<a href="{}?clinician_id={}">Edit pattern</a>', url, obj.pk
        )
    pattern_link.short_description = "Pattern"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        outside = self._entries_outside_window(obj)
        if outside:
            messages.warning(
                request,
                f"{obj.name} has {outside} rota entr"
                f"{'y' if outside == 1 else 'ies'} outside "
                f"{obj.start_date or 'any start'} – {obj.end_date or 'any end'}. "
                f"Nothing has been deleted; review them on the grid."
            )

    @staticmethod
    def _entries_outside_window(clinician):
        from django.db.models import Q
        if not clinician.start_date and not clinician.end_date:
            return 0
        q = Q()
        if clinician.start_date:
            q |= Q(day__lt=clinician.start_date)
        if clinician.end_date:
            q |= Q(day__gt=clinician.end_date)
        return RotaEntry.objects.filter(q, clinician=clinician).count()


@admin.register(SessionType)
class SessionTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "category", "colour_swatch",
                    "fairness_tracked", "pin_on_day_view")
    list_filter = ("pin_on_day_view", "fairness_tracked", "category")
    filter_horizontal = ("allowed_clinicians", "allowed_groups", "blocks_same_day")
    readonly_fields = ("legacy_colour",)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "colour":
            kwargs["widget"] = TintSwatchSelect
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    @admin.display(description="Colour")
    def colour_swatch(self, obj):
        tint = obj.tint
        return format_html(
            '<span style="display:inline-block; padding:2px 10px; '
            'border-radius:6px; background:{}; color:{}">{}</span>',
            tint.bg, tint.fg, tint.label)


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

        # Two names because raw_date answers two different questions and
        # conflating them was the bug: raw_date (POST-or-GET) is what
        # RENDERING should use -- it is how the post-save redirect restores
        # the admin's context (?clinician_id=&effective_from=) on the next
        # GET, and a first visit with no date at all should still default to
        # today without erroring. posted_date (POST body only, no GET
        # fallback) is the only thing a SAVE decision may look at: the form
        # has no method="get" sibling any more, so anything the query string
        # still carries is leftover context from a previous request, not
        # something the admin just submitted. Without this split, clearing
        # the date field and pressing Save on a URL the app's own redirect
        # put you on (carrying a still-valid effective_from) silently wrote
        # a row at that stale date -- raw_date fell back to the query string,
        # so "not raw_date" never noticed the field was cleared.
        raw_date = (request.POST.get("effective_from")
                    or request.GET.get("effective_from") or "")
        posted_date = request.POST.get("effective_from") or ""
        date_error = ""
        if raw_date:
            try:
                effective_from = date.fromisoformat(raw_date)
            except ValueError:
                # Never fall back to today: today is the value that overwrites
                # the live pattern, so a typo would be destructive.
                effective_from = date.today()
                date_error = (f"{raw_date!r} is not a date (use YYYY-MM-DD). "
                              f"Nothing was saved.")
        else:
            # A harmless display default for rendering (a first visit, or a
            # load with no date chosen yet).
            effective_from = date.today()

        action = request.POST.get("action")
        if request.method == "POST" and action == "save" and clinician \
                and not posted_date:
            # An explicit save with no date in the request body -- field
            # cleared, or the key omitted entirely -- must be refused exactly
            # like a malformed one, regardless of what effective_from the
            # query string still holds from a previous redirect. Falling
            # through to the date.today() display default here would
            # reproduce the exact disaster this task exists to remove, just
            # through a narrower door.
            date_error = "Effective date is required. Nothing was saved."

        if request.method == "POST" and action == "save" and clinician \
                and not date_error:
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
        history = []
        if clinician:
            # The pattern in force *on* the chosen date, not the day before
            # it. For a date with no rows of its own the two are identical,
            # so the add-a-future-change flow still opens on the pattern it
            # would be changing. For a date that already has rows -- exactly
            # what the Pattern history table invites an admin to click --
            # the day-before view rendered those rows' own sessions
            # unticked, and Save then posted the boxes as rendered and
            # flipped them to works=False in place. Destroying the value it
            # had just been asked to show.
            #
            # bulk_set_pattern's own `prior` lookup still compares against
            # the day before, on purpose: that comparison is what makes a
            # save write only genuine differences, and it is not what the
            # admin is looking at.
            in_force = current_pattern(clinician, effective_from)
            grid = [
                {
                    "weekday": weekday,
                    "label": WEEKDAY_LABELS[weekday],
                    "am_checked": in_force.get((weekday, "AM"), False),
                    "pm_checked": in_force.get((weekday, "PM"), False),
                }
                for weekday in range(7)
            ]
            history = self._pattern_history(clinician)

        context = {
            **self.admin_site.each_context(request),
            "title": "Bulk edit clinician pattern",
            "opts": self.model._meta,
            "clinicians": clinicians,
            "clinician": clinician,
            "effective_from": effective_from,
            "date_error": date_error,
            "grid": grid,
            "history": history,
        }
        return render(request, "admin/rota/patternslot/bulk_form.html", context)

    @staticmethod
    def _pattern_history(clinician):
        """Every effective_from and what it sets, so the editor stops hiding
        the fact that other dates exist."""
        by_date = {}
        for row in PatternSlot.objects.filter(clinician=clinician).order_by(
            "effective_from", "weekday", "part"
        ):
            by_date.setdefault(row.effective_from, []).append(
                f"{WEEKDAY_LABELS[row.weekday][:3]} {row.part}"
                f"{'' if row.works else ' off'}")
        return [{"effective_from": d, "sessions": ", ".join(v)}
                for d, v in sorted(by_date.items())]


@admin.register(CoverageRule)
class CoverageRuleAdmin(admin.ModelAdmin):
    list_display = ("session_type", "unit", "frequency", "parts", "weekdays",
                    "months", "count", "priority")


@admin.register(TraineeStageRule)
class TraineeStageRuleAdmin(admin.ModelAdmin):
    list_display = ("stage", "vts_per_week", "sdl_per_week",
                    "mentoring_per_week", "vts_weekday", "vts_part")

    def has_delete_permission(self, request, obj=None):
        # The four rows are reference data seeded by migration, not user
        # content — deleting one 500s the trainee report and every fill for
        # trainees at that stage (rota/models/trainees.py::stage_rule).
        return False


@admin.register(RecurringCommitment)
class RecurringCommitmentAdmin(admin.ModelAdmin):
    list_display = ("clinician", "weekday", "part", "session_type", "site",
                    "interval_weeks", "active_from", "active_until")
    list_filter = ("clinician",)


admin.site.register(ClosedDay)
admin.site.register(DayNote)


@admin.register(PracticeSettings)
class PracticeSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        """PracticeSettings is a pk=1 singleton by convention
        (PracticeSettings.load()) — refuse a second row."""
        return not PracticeSettings.objects.exists()


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


@admin.register(SwapRequest)
class SwapRequestAdmin(admin.ModelAdmin):
    list_display = ("proposer", "colleague", "status", "created_at")
    list_filter = ("status",)
