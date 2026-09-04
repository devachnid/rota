"""The admin's bespoke pages, as unfold custom pages.

Each is a class-based view carrying `title` and `permission_required`,
mounted under its ModelAdmin's get_urls() through admin_site.admin_view.
The pattern editor's behaviour is the old bulk_view's, moved not changed:
every guard in it was paid for.
"""

from datetime import date, timedelta

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import TemplateView
from unfold.views import UnfoldModelAdminViewMixin

from rota.models import (BreatheAbsence, BreatheLeaveMapping, BreatheSyncRun,
                         Clinician, Part, PatternSlot)
from rota.services.breathe import client as breathe_client
from rota.services.patterns import bulk_set_pattern, current_pattern

WEEKDAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                  "Saturday", "Sunday"]


def clinicians_without_a_pattern():
    """Active, not a locum, no pattern rows at all — the dashboard's
    'working patterns' step and the editor's ?missing=1 share this."""
    return (Clinician.objects.filter(active=True, group__is_locum_group=False,
                                     pattern_slots__isnull=True)
            .order_by("name").distinct())


def pattern_history(clinician):
    by_date = {}
    for row in PatternSlot.objects.filter(clinician=clinician).order_by(
            "effective_from", "weekday", "part"):
        by_date.setdefault(row.effective_from, []).append(
            f"{WEEKDAY_LABELS[row.weekday][:3]} {row.part}{'' if row.works else ' off'}")
    return [{"effective_from": d, "sessions": ", ".join(v)}
            for d, v in sorted(by_date.items())]


class PatternEditorView(UnfoldModelAdminViewMixin, TemplateView):
    title = "Pattern editor"
    permission_required = ("rota.change_patternslot",)
    template_name = "admin/rota/patternslot/editor.html"

    def get(self, request, *args, **kwargs):
        return self._respond(request)

    def post(self, request, *args, **kwargs):
        return self._respond(request)

    def _respond(self, request):
        missing = list(clinicians_without_a_pattern()) if request.GET.get("missing") else []
        clinicians = Clinician.objects.filter(active=True).order_by("name")
        clinician = None
        clinician_id = (request.POST.get("clinician_id")
                        or request.GET.get("clinician_id"))
        if not clinician_id and missing:
            clinician_id = missing[0].pk
        if clinician_id:
            clinician = get_object_or_404(Clinician, pk=clinician_id)

        # raw_date is for RENDERING (POST or the query string the post-save
        # redirect carries); posted_date is the only thing a SAVE may look
        # at. Conflating them was the overwrite bug: a cleared field fell
        # back to a stale query-string date.
        raw_date = (request.POST.get("effective_from")
                    or request.GET.get("effective_from") or "")
        posted_date = request.POST.get("effective_from") or ""
        date_error = ""
        if raw_date:
            try:
                effective_from = date.fromisoformat(raw_date)
            except ValueError:
                effective_from = date.today()
                date_error = (f"{raw_date!r} is not a date (use YYYY-MM-DD). "
                              f"Nothing was saved.")
        else:
            effective_from = date.today()

        action = request.POST.get("action")
        saving = request.method == "POST" and action == "save" and clinician
        if saving and not posted_date:
            date_error = "Effective date is required. Nothing was saved."

        if saving and not date_error:
            desired = {(weekday, part): f"d{weekday}_{part}" in request.POST
                       for weekday in range(7) for part in Part.values}
            changed = bulk_set_pattern(clinician, effective_from, desired)
            text = (f"Saved pattern for {clinician.name} effective "
                    f"{effective_from} ({changed} slot(s) changed).")
            query = f"?clinician_id={clinician.pk}&effective_from={effective_from.isoformat()}"
            if request.GET.get("missing"):
                remaining = [c for c in clinicians_without_a_pattern() if c.pk != clinician.pk]
                if remaining:
                    text += f" Next: {remaining[0].name}."
                    query = f"?clinician_id={remaining[0].pk}&missing=1"
                else:
                    text += " Everyone has a pattern now."
            messages.success(request, text)
            return redirect(f"{request.path}{query}")

        grid, history = None, []
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
            grid = [{"weekday": w, "label": WEEKDAY_LABELS[w],
                     "am_checked": in_force.get((w, "AM"), False),
                     "pm_checked": in_force.get((w, "PM"), False)} for w in range(7)]
            history = pattern_history(clinician)

        context = self.get_context_data(
            clinicians=clinicians, clinician=clinician, effective_from=effective_from,
            date_error=date_error, grid=grid, history=history, missing=missing)
        return self.render_to_response(context)


def unmapped_absence_count():
    """Stored BreatheAbsence rows whose (kind, reason) has no mapping row
    and whose (kind, "") default also has no row — i.e. absences the
    resolver currently renders as empty cells, findable nowhere else."""
    mapping = BreatheLeaveMapping.as_dict()
    return sum(1 for kind, reason in BreatheAbsence.objects.values_list("kind", "reason")
               if (kind, reason) not in mapping and (kind, "") not in mapping)


class BreatheStatusView(UnfoldModelAdminViewMixin, TemplateView):
    title = "Sync status"
    permission_required = ("rota.view_breathesyncrun",)
    template_name = "admin/rota/breathesyncrun/status.html"

    def get_context_data(self, **kwargs):
        last_ok = BreatheSyncRun.objects.filter(ok=True).first()
        last = BreatheSyncRun.objects.first()
        return super().get_context_data(
            configured=breathe_client.from_settings() is not None,
            last_ok=last_ok,
            last_error=last if (last and not last.ok) else None,
            unlinked=Clinician.objects.filter(active=True, breathe_employee_id=None)
                                      .order_by("name"),
            unmapped_count=unmapped_absence_count(),
            runs=BreatheSyncRun.objects.all()[:20],
            **kwargs)
