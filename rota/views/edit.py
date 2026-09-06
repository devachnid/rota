from datetime import date

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from rota.models import (Clinician, DayNote, LocumRequirement, Part,
                         PracticeSettings, RotaEntry, SessionType, Site,
                         TraineeProfile)
from rota.services import entries as entries_svc
from rota.services import locums as locums_svc
from rota.views.decorators import admin_required, parse_errors_as_400


def _refresh():
    return HttpResponse(status=204, headers={"HX-Refresh": "true"})


def _clean_part(part):
    """Reject a part outside Part.values so a hand-crafted request can't
    create a row the grid never renders (it only looks for AM/PM)."""
    if part not in Part.values:
        raise ValueError(f"Invalid part: {part!r}")
    return part


CATEGORY_ORDER = (SessionType.Category.CLINICAL, SessionType.Category.NON_CLINICAL,
                  SessionType.Category.ABSENCE)


def type_groups():
    """Session types for a dropdown, grouped Clinical / Non-clinical /
    Absence — the order someone adding a session thinks in — each by name.
    SessionType.Meta.ordering sorts the category *values*, and "ABSENCE"
    sorts first, which is how leave came to head the list."""
    by_category = {c: [] for c in CATEGORY_ORDER}
    for t in SessionType.objects.order_by("name"):
        by_category.setdefault(t.category, []).append(t)
    return [(SessionType.Category(c).label, ts) for c, ts in by_category.items() if ts]


def _current_partner_id(entry):
    """The other half of the pair this entry is in, if it is in one."""
    if entry is None or not entry.companion_group:
        return None
    return (RotaEntry.objects.filter(companion_group=entry.companion_group)
            .exclude(pk=entry.pk).values_list("clinician_id", flat=True).first())


def _natural_partner_id(clinician):
    """Who a mentoring session is most likely with: a trainee's trainer, or
    a trainer's only trainee. None when there is no obvious answer."""
    trainer_id = (TraineeProfile.objects.filter(clinician=clinician)
                  .values_list("trainer_id", flat=True).first())
    if trainer_id:
        return trainer_id
    trainees = list(TraineeProfile.objects.filter(trainer=clinician)
                    .values_list("clinician_id", flat=True))
    return trainees[0] if len(trainees) == 1 else None


def _cell_context(clinician, day, part, note=None, site_id=None, **extra):
    groups = type_groups()
    types = [t for _, ts in groups for t in ts]
    entry = RotaEntry.objects.filter(
        clinician=clinician, day=day, part=part).first()
    settings = PracticeSettings.load()
    # What the Session dropdown opens on: what was just posted (a warning
    # re-render), else what the cell holds, else the practice's default
    # fill type — the thing most often being added.
    selected_id = (extra.pop("selected_type", None)
                   or (entry.session_type_id if entry else settings.default_fill_session_type_id))
    # The "With" field for a mentoring session (only offered when the
    # practice has named a mentoring type): what was just posted ("" is a
    # deliberate blank), else the current pair, else the natural partner.
    mentoring_id = settings.mentoring_session_type_id
    partner_id = extra.pop("partner_id", None)
    if mentoring_id and partner_id is None:
        partner_id = _current_partner_id(entry) or _natural_partner_id(clinician)
    return {
        "clinician": clinician, "day": day, "part": part,
        "entry": entry,
        "type_groups": groups,
        "selected_id": selected_id,
        "ineligible_ids": [t.id for t in types if not t.is_eligible(clinician)],
        "mentoring_id": mentoring_id,
        "partner_id": partner_id,
        "partners": (Clinician.objects.filter(active=True, group__is_locum_group=False)
                     .exclude(pk=clinician.pk).order_by("name") if mentoring_id else []),
        "sites": Site.objects.all(),
        "note": note if note is not None else (entry.note if entry else ""),
        "site_id": site_id if site_id is not None else (entry.site_id if entry else None),
        **extra,
    }


@admin_required
@parse_errors_as_400
def cell_form(request, clinician_id, day, part):
    clinician = get_object_or_404(Clinician, pk=clinician_id)
    return render(request, "rota/_cell_form.html",
                  _cell_context(clinician, date.fromisoformat(day), part))


@admin_required
@parse_errors_as_400
@require_POST
def assign(request):
    clinician = get_object_or_404(Clinician, pk=request.POST["clinician_id"])
    day = date.fromisoformat(request.POST["day"])
    part = _clean_part(request.POST["part"])
    st = get_object_or_404(SessionType, pk=request.POST["session_type_id"])
    site = Site.objects.filter(pk=request.POST.get("site_id") or None).first()
    note = request.POST.get("note", "")
    # A mentoring session is a pair. The partner is read only for the
    # practice's mentoring type: the field is on the form whatever is
    # selected (hidden, so a change of mind is not a lost choice).
    partner = None
    if st.id == PracticeSettings.load().mentoring_session_type_id and request.POST.get("partner_id"):
        partner = get_object_or_404(Clinician, pk=request.POST["partner_id"], active=True)
        if partner.pk == clinician.pk:
            raise ValueError("A mentoring pair needs two different people.")

    def again(warning, **flags):
        return render(request, "rota/_cell_form.html", _cell_context(
            clinician, day, part, note=note, site_id=site.id if site else None,
            warning=warning, selected_type=st.id,
            partner_id=partner.id if partner else "", **flags))

    if not st.is_eligible(clinician) and not request.POST.get("confirm"):
        return again(f"{clinician.name} is not usually eligible for {st.name}. "
                     "Save again to override.",
                     confirm=True, replace=bool(request.POST.get("replace")))
    parts = ["AM", "PM"] if request.POST.get("full_day") else [part]
    if partner is not None:
        # Writing the pair overwrites whatever the partner holds in that
        # slot, so anything other than the same type is asked about first.
        held = (RotaEntry.objects.filter(clinician=partner, day=day, part__in=parts)
                .exclude(session_type=st).select_related("session_type")
                .order_by("part").first())
        if held and not request.POST.get("replace"):
            return again(f"{partner.name} already has {held.session_type.name} on "
                         f"{day:%a %-d %b} {held.part}. Save again to replace it "
                         f"with {st.name}.",
                         confirm=bool(request.POST.get("confirm")), replace=True)
        for p in parts:
            entries_svc.assign_pair(request.user, day, p, clinician, partner, st,
                                    site=site, note=note, manually_set=True)
        return _refresh()
    if request.POST.get("full_day"):
        entries_svc.assign_full_day(request.user, clinician, day, st,
                                    site=site, note=note, manually_set=True)
    else:
        entries_svc.assign(request.user, clinician, day, part, st, site=site,
                           note=note, manually_set=True)
    return _refresh()


@admin_required
@parse_errors_as_400
@require_POST
def clear(request):
    clinician = get_object_or_404(Clinician, pk=request.POST["clinician_id"])
    entries_svc.clear(request.user, clinician,
                      date.fromisoformat(request.POST["day"]),
                      _clean_part(request.POST["part"]))
    return _refresh()


@admin_required
@parse_errors_as_400
@require_POST
def publish(request):
    entries_svc.publish_range(request.user,
                              date.fromisoformat(request.POST["start"]),
                              date.fromisoformat(request.POST["end"]))
    return _refresh()


@admin_required
@parse_errors_as_400
def daynote_form(request, day):
    d = date.fromisoformat(day)
    note = DayNote.objects.filter(day=d).first()
    return render(request, "rota/_daynote_form.html", {"day": d, "note": note})


@admin_required
@parse_errors_as_400
@require_POST
def daynote_save(request):
    d = date.fromisoformat(request.POST["day"])
    text = request.POST.get("text", "").strip()
    if text:
        DayNote.objects.update_or_create(day=d, defaults={"text": text})
    else:
        DayNote.objects.filter(day=d).delete()
    return _refresh()


def _locum_form_context(req=None, day=None, part=None):
    return {
        "req": req,
        "day": req.day if req else day,
        "part": req.part if req else part,
        "type_groups": type_groups(),
        "locums": Clinician.objects.filter(active=True,
                                           group__is_locum_group=True),
        "coverable": Clinician.objects.filter(
            active=True, group__is_locum_group=False).order_by("name"),
        "statuses": LocumRequirement.Status.choices,
    }


@admin_required
@parse_errors_as_400
def locum_new(request):
    return render(request, "rota/_locum_form.html", _locum_form_context(
        day=date.fromisoformat(request.GET["day"]), part=request.GET["part"]))


@admin_required
@parse_errors_as_400
def locum_form(request, pk):
    req = get_object_or_404(LocumRequirement, pk=pk)
    return render(request, "rota/_locum_form.html", _locum_form_context(req=req))


@admin_required
@parse_errors_as_400
@require_POST
def locum_save(request):
    st = get_object_or_404(SessionType, pk=request.POST["session_type_id"])
    clinician = Clinician.objects.filter(
        pk=request.POST.get("clinician_id") or None).first()
    covering = Clinician.objects.filter(
        pk=request.POST.get("covering_id") or None, active=True).first()
    day = date.fromisoformat(request.POST["day"])
    part = _clean_part(request.POST["part"])
    try:
        locums_svc.save_requirement(
            request.user,
            pk=request.POST.get("pk") or None,
            day=day,
            part=part,
            session_type=st,
            status=request.POST["status"],
            details=request.POST.get("details", ""),
            clinician=clinician,
            covering=covering,
        )
    except ValueError as e:
        req = LocumRequirement.objects.filter(
            pk=request.POST.get("pk") or None
        ).first()
        ctx = _locum_form_context(
            req=req,
            day=day,
            part=part,
        )
        ctx["warning"] = str(e)
        return render(request, "rota/_locum_form.html", ctx)
    return _refresh()
