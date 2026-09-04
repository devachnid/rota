from datetime import date, timedelta

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.utils import NestedObjects
from django.db import router
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.text import capfirst

from unfold.admin import ModelAdmin, StackedInline, TabularInline
from unfold.contrib.filters.admin import RangeDateFilter
from unfold.decorators import display

from .models import (BreatheAbsence, BreatheLeaveMapping, BreatheSyncRun,
                     Clinician, ClinicianGroup, ClosedDay, CoverageRule,
                     DayNote, LocumRequirement, Part,
                     PatternSlot, PracticeSettings, RecurringCommitment, RotaEntry, RotaEntryLog,
                     SessionType, Site, SwapRequest, TraineeProfile, TraineeStageRule)
from .services.patterns import bulk_set_pattern, current_pattern
from .services.breathe import client as breathe_client, sync as breathe_sync
from .admin_forms import WEEKDAYS, CoverageRuleForm, PracticeSettingsForm
from .admin_widgets import (BreatheEmployeeSelect, TintSwatchSelect,
                            breathe_employees, employee_label)

WEEKDAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                  "Saturday", "Sunday"]

WEEKDAY_ABBR = [d[:3] for d in WEEKDAY_LABELS]


def pattern_text(rows, today):
    """'Mon AM/PM · Tue AM — since 1 Sep 2025' from a clinician's pattern
    rows, applying the in-force rule (latest effective_from on or before
    today wins per weekday/part) in Python so a list page costs no query
    per row. 'No pattern yet' when nothing is in force."""
    in_force = {}
    since = None
    for row in rows:
        if row.effective_from > today:
            continue
        key = (row.weekday, row.part)
        if key not in in_force or row.effective_from >= in_force[key].effective_from:
            in_force[key] = row
        if since is None or row.effective_from > since:
            since = row.effective_from
    worked = {}
    for (weekday, part), row in in_force.items():
        if row.works:
            worked.setdefault(weekday, []).append(part)
    if not worked:
        return "No pattern yet"
    days = " · ".join(
        f"{WEEKDAY_ABBR[wd]} {'/'.join(sorted(parts, key=('AM', 'PM').index))}"
        for wd, parts in sorted(worked.items()))
    return f"{days} — since {since.strftime('%-d %b %Y')}"


@admin.register(ClinicianGroup)
class ClinicianGroupAdmin(ModelAdmin):
    list_display = ("name", "display_order", "min_per_session", "is_locum_group")
    list_editable = ("display_order", "min_per_session")
    search_fields = ("name",)
    fieldsets = (
        (None, {
            "fields": ("name", "display_order"),
            "description": "Groups order the grid and drive a staffing warning. "
                           "Lower display order appears first.",
        }),
        ("Staffing", {
            "fields": ("min_per_session", "is_locum_group"),
            "description": "Set a minimum to warn when fewer of this group are in. "
                           "Exactly one group is the locum group: its members appear "
                           "on the grid only in weeks they hold a session.",
        }),
    )


class TraineeProfileInline(StackedInline):
    model = TraineeProfile
    fk_name = "clinician"
    extra = 0
    verbose_name = "Trainee profile"
    verbose_name_plural = "Trainee profile"


class RecurringCommitmentInline(TabularInline):
    model = RecurringCommitment
    fk_name = "clinician"
    extra = 0
    fields = ("session_type", "weekday", "part", "site", "active_from",
              "active_until", "interval_weeks")
    verbose_name_plural = "Recurring commitments"

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "weekday":
            kwargs["widget"] = forms.Select(choices=WEEKDAYS)
        return super().formfield_for_dbfield(db_field, request, **kwargs)


class BreatheLinkedFilter(admin.SimpleListFilter):
    title = "Breathe"
    parameter_name = "breathe"

    def lookups(self, request, model_admin):
        # Labels avoid the bare word "Linked": a clinician can genuinely be
        # named that, and the sidebar renders every option on every page —
        # including the "not linked" filtered view — so a literal "Linked"
        # label would show up there regardless of which clinicians matched.
        return [("linked", "Has a link"), ("unlinked", "No link")]

    def queryset(self, request, qs):
        if self.value() == "linked":
            return qs.exclude(breathe_employee_id=None)
        if self.value() == "unlinked":
            return qs.filter(breathe_employee_id=None)
        return qs


@admin.register(Clinician)
class ClinicianAdmin(ModelAdmin):
    list_display = ("name", "initials", "group", "active", "is_trainer",
                    "pattern_column", "breathe_link")
    list_filter = ("group", "active", "is_trainer", BreatheLinkedFilter)
    search_fields = ("name", "initials", "user__email")
    inlines = [TraineeProfileInline, RecurringCommitmentInline]
    actions = ["deactivate_clinicians"]
    readonly_fields = ("pattern_summary",)
    fieldsets = (
        ("Who", {
            "fields": ("name", "initials", "group", "user"),
            "description": "Initials are what the grid shows. Link the login "
                           "account so this person sees their own schedule.",
        }),
        ("Availability", {
            "fields": ("active", "start_date", "end_date", "pattern_summary"),
            "description": "Untick Active to take someone out of every eligibility "
                           "pool while keeping their history — the alternative to "
                           "deleting. Dates bound when they can be scheduled.",
        }),
        ("Roles", {"fields": ("is_trainer",)}),
        ("Leave from Breathe", {
            "fields": ("breathe_employee_id",),
            "description": "Leave is read from Breathe for linked clinicians only. "
                           "An unlinked clinician is treated as always available.",
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("group", "user") \
            .prefetch_related("pattern_slots")

    @admin.display(description="Pattern")
    def pattern_column(self, obj):
        text = pattern_text(obj.pattern_slots.all(), date.today())
        if text == "No pattern yet":
            return format_html('<span style="color: var(--color-primary-700)">{}</span>', text)
        return text

    @admin.display(description="Working pattern")
    def pattern_summary(self, obj):
        if obj.pk is None:
            return "Save the clinician first, then set their pattern."
        text = pattern_text(obj.pattern_slots.all(), date.today())
        url = reverse("admin:rota_patternslot_bulk")
        return format_html('{} &nbsp; <a href="{}?clinician_id={}">Edit pattern</a>',
                           text, url, obj.pk)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "breathe_employee_id":
            employees = breathe_employees()
            if employees is None:
                field = super().formfield_for_dbfield(db_field, request, **kwargs)
                field.help_text = ("Could not reach Breathe, so this is the raw employee id. "
                                   "The dropdown returns when Breathe is reachable.")
                return field
            kwargs["widget"] = BreatheEmployeeSelect(employees)
            kwargs["help_text"] = "The Breathe employee whose leave this clinician's is."
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Suggest by exact email match — only for a clinician with no link, and
        # only as an initial value the admin must still submit.
        #
        # Setting `field.initial` (form.base_fields[...].initial) has no
        # effect here: for a change view Django builds the form as
        # ModelForm(instance=obj), and BaseModelForm.__init__ seeds
        # self.initial from model_to_dict(instance) *before* anything looks
        # at the field's own .initial — so self.initial already holds
        # breathe_employee_id: None, and dict.get(key, default) returns that
        # stored None rather than falling through to field.initial. The
        # suggestion has to land in self.initial on the bound form instance
        # instead, which is why this subclasses rather than touching
        # base_fields.
        if obj is not None and obj.breathe_employee_id is None and obj.user_id:
            employees = breathe_employees() or []
            email = (obj.user.email or "").lower()
            match = next((e for e in employees if (e.get("email") or "").lower() == email), None)
            if match and "breathe_employee_id" in form.base_fields:
                suggested_id = match["id"]

                class SuggestingForm(form):
                    def __init__(self, *args, **kw):
                        super().__init__(*args, **kw)
                        # Only the empty GET render, never a submitted POST —
                        # a bound form's initial is irrelevant to what gets
                        # saved, but leaving this unconditional would still
                        # be harmless; the guard just documents the intent.
                        if not self.is_bound:
                            self.initial["breathe_employee_id"] = suggested_id

                return SuggestingForm
        return form

    @admin.display(description="Breathe")
    def breathe_link(self, obj):
        if obj.breathe_employee_id is None:
            return format_html(
                '<span style="color: var(--muted, #6b7280)">{}</span>', "not linked")
        employees = breathe_employees() or []
        e = next((x for x in employees if x["id"] == obj.breathe_employee_id), None)
        return employee_label(e) if e else f"#{obj.breathe_employee_id}"

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
        # Everything else cascades: pattern slots, recurring commitments,
        # the trainee profile, and swap requests — including ones where
        # this clinician was the *colleague*, which touches someone else's
        # history. Locum bookings survive with the name set to null.
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
class SessionTypeAdmin(ModelAdmin):
    list_display = ("name", "code", "category", "colour_swatch",
                    "fairness_tracked", "pin_on_day_view")
    list_filter = ("pin_on_day_view", "fairness_tracked", "category")
    search_fields = ("name", "code")
    filter_horizontal = ("allowed_clinicians", "allowed_groups", "blocks_same_day")
    readonly_fields = ("legacy_colour",)
    fieldsets = (
        ("Identity", {"fields": ("name", "code", "colour")}),
        ("Where it appears", {
            "fields": ("category", "pin_on_day_view", "default_site"),
            "description": "Pin the roles someone opens the day view to check — Duty "
                           "above all. Default site is stamped on entries the fill "
                           "engine creates.",
        }),
        ("Fairness", {"fields": ("fairness_tracked",)}),
        ("Who may do it", {
            "fields": ("allowed_clinicians", "allowed_groups"),
            "description": "Leave both empty and anyone may do it. Otherwise only the "
                           "named clinicians and groups are eligible.",
        }),
        ("Clashes", {
            "fields": ("blocks_same_day",),
            "description": "A clinician holding this type on a day is not "
                           "auto-assigned any of these the same day.",
        }),
        ("History", {"fields": ("legacy_colour",), "classes": ("collapse",)}),
    )

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


@admin.register(Site)
class SiteAdmin(ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


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
class CoverageRuleAdmin(ModelAdmin):
    form = CoverageRuleForm
    list_display = ("session_type", "unit", "frequency", "parts", "weekdays",
                    "months", "count", "priority")
    list_editable = ("priority",)
    list_filter = ("session_type", "frequency", "unit")
    fieldsets = (
        ("What", {
            "fields": ("session_type", "unit", "frequency", "count"),
            "description": "A worked example: Duty, per full day, per slot, count 1, "
                           "priority 1 means one clinician holds Duty all day, every "
                           "open day, and this rule is filled before any other.",
        }),
        ("When", {"fields": ("parts", "weekdays", "months", "preferred_weekdays")}),
        ("Order", {
            "fields": ("priority",),
            "description": "Lower fills first. When two rules want the same person, "
                           "the lower number gets them.",
        }),
    )


@admin.register(TraineeStageRule)
class TraineeStageRuleAdmin(ModelAdmin):
    list_display = ("stage", "vts_per_week", "sdl_per_week",
                    "mentoring_per_week", "vts_weekday", "vts_part")
    list_editable = ("vts_per_week", "sdl_per_week", "mentoring_per_week")

    def has_delete_permission(self, request, obj=None):
        # The four rows are reference data seeded by migration, not user
        # content — deleting one 500s the trainee report and every fill for
        # trainees at that stage (rota/models/trainees.py::stage_rule).
        return False


@admin.register(TraineeProfile)
class TraineeProfileAdmin(ModelAdmin):
    list_display = ("clinician", "stage", "wte_percent", "trainer",
                    "placement_start", "placement_end")
    list_filter = ("stage",)
    search_fields = ("clinician__name",)


@admin.register(RecurringCommitment)
class RecurringCommitmentAdmin(ModelAdmin):
    list_display = ("clinician", "weekday", "part", "session_type", "site",
                    "interval_weeks", "active_from", "active_until")
    list_filter = ("clinician", "session_type", ("active_from", RangeDateFilter))
    search_fields = ("clinician__name",)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "weekday":
            kwargs["widget"] = forms.Select(choices=WEEKDAYS)
        return super().formfield_for_dbfield(db_field, request, **kwargs)


@admin.register(ClosedDay)
class ClosedDayAdmin(ModelAdmin):
    list_display = ("day", "reason")
    date_hierarchy = "day"
    search_fields = ("reason",)
    ordering = ("-day",)


@admin.register(DayNote)
class DayNoteAdmin(ModelAdmin):
    list_display = ("day", "text")
    date_hierarchy = "day"
    search_fields = ("text",)
    ordering = ("-day",)


@admin.register(PracticeSettings)
class PracticeSettingsAdmin(ModelAdmin):
    form = PracticeSettingsForm
    fieldsets = (
        ("Opening", {"fields": ("open_weekdays",)}),
        ("Fill", {"fields": ("min_clinical_per_session", "default_fill_session_type")}),
        ("Trainees", {
            "fields": ("vts_session_type", "sdl_session_type", "mentoring_session_type"),
            "description": "Only for a practice with trainees. A blank type skips that "
                           "pass of the fill — no error.",
        }),
    )

    def has_add_permission(self, request):
        return not PracticeSettings.objects.exists()

    def changelist_view(self, request, extra_context=None):
        """No changelist of one row: open the singleton."""
        return redirect("admin:rota_practicesettings_change",
                        PracticeSettings.load().pk)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not obj.open_weekday_list():
            messages.warning(request, "The surgery is open on no days: the grid "
                                      "will show nothing until a weekday is ticked.")


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
    list_display = ("day", "part", "session_type", "status", "clinician", "covering")
    list_filter = ("status",)


@admin.register(SwapRequest)
class SwapRequestAdmin(admin.ModelAdmin):
    list_display = ("proposer", "colleague", "status", "created_at")
    list_filter = ("status",)


@admin.register(BreatheAbsence)
class BreatheAbsenceAdmin(admin.ModelAdmin):
    list_display = ("clinician", "kind", "reason", "start_date", "end_date",
                    "half_start_am_pm", "half_end_am_pm")
    list_filter = ("kind",)
    readonly_fields = [f.name for f in BreatheAbsence._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(BreatheLeaveMapping)
class BreatheLeaveMappingAdmin(admin.ModelAdmin):
    list_display = ("kind", "reason", "session_type")
    list_filter = ("kind",)

    def has_delete_permission(self, request, obj=None):
        # A row with reason == "" is a kind's default. Deleting it is one
        # click from every absence of that kind rendering an empty cell —
        # the resolver falls through (kind, reason) -> (kind, "") and, with
        # neither present, renders nothing (see BreatheSyncRunAdmin's
        # "unmapped absences" count below). Reason-specific rows stay
        # deletable; they only narrow a kind's default, they are not it.
        if obj is not None and obj.reason == "":
            return False
        return super().has_delete_permission(request, obj)


def _unmapped_absence_count():
    """Stored BreatheAbsence rows whose (kind, reason) has no mapping row
    and whose (kind, "") default also has no row — i.e. absences the
    resolver currently renders as empty cells, findable nowhere else."""
    mapping = BreatheLeaveMapping.as_dict()
    return sum(
        1 for kind, reason in BreatheAbsence.objects.values_list("kind", "reason")
        if (kind, reason) not in mapping and (kind, "") not in mapping
    )


@admin.register(BreatheSyncRun)
class BreatheSyncRunAdmin(admin.ModelAdmin):
    list_display = ("started", "ok", "n_deduped", "n_unlinked", "error")
    readonly_fields = [f.name for f in BreatheSyncRun._meta.fields]
    change_list_template = "admin/rota/breathesyncrun/change_list.html"

    def has_add_permission(self, request):
        return False

    def get_urls(self):
        return [path("refresh/", self.admin_site.admin_view(self.refresh),
                     name="rota_breathesyncrun_refresh")] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        last_ok = BreatheSyncRun.objects.filter(ok=True).first()
        last = BreatheSyncRun.objects.first()
        extra = {
            "last_ok": last_ok,
            "last_error": last if (last and not last.ok) else None,
            "unlinked": Clinician.objects.filter(active=True, breathe_employee_id=None).order_by("name"),
            "configured": breathe_client.from_settings() is not None,
            "unmapped_count": _unmapped_absence_count(),
        }
        extra.update(extra_context or {})
        return super().changelist_view(request, extra_context=extra)

    def refresh(self, request):
        if request.method != "POST":
            return redirect("admin:rota_breathesyncrun_changelist")
        recent = BreatheSyncRun.objects.filter(
            started__gte=timezone.now() - timedelta(seconds=60)).exists()
        if recent:
            messages.warning(request, "A sync ran less than a minute ago; not running another.")
            return redirect("admin:rota_breathesyncrun_changelist")
        client = breathe_client.from_settings()
        if client is None:
            messages.error(request, "Breathe is not configured (BREATHE_API_KEY unset).")
            return redirect("admin:rota_breathesyncrun_changelist")
        run = breathe_sync.run(client)
        if run.ok:
            messages.success(request, f"Synced: {run.n_deduped} absences, {run.n_unlinked} for unlinked employees.")
        else:
            messages.error(request, f"Sync failed: {run.error}")
        return redirect("admin:rota_breathesyncrun_changelist")
