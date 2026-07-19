from datetime import date

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from rota.models import (Clinician, DayNote, LocumRequirement, RotaEntry,
                         SessionType, Site)
from rota.services import entries as entries_svc
from rota.services import locums as locums_svc
from rota.views.decorators import admin_required


def _refresh():
    return HttpResponse(status=204, headers={"HX-Refresh": "true"})


def _cell_context(clinician, day, part, **extra):
    types = SessionType.objects.all().order_by("category", "name")
    return {
        "clinician": clinician, "day": day, "part": part,
        "entry": RotaEntry.objects.filter(
            clinician=clinician, day=day, part=part).first(),
        "session_types": types,
        "ineligible_ids": [t.id for t in types if not t.is_eligible(clinician)],
        "sites": Site.objects.all(),
        **extra,
    }


@admin_required
def cell_form(request, clinician_id, day, part):
    clinician = get_object_or_404(Clinician, pk=clinician_id)
    return render(request, "rota/_cell_form.html",
                  _cell_context(clinician, date.fromisoformat(day), part))


@admin_required
@require_POST
def assign(request):
    clinician = get_object_or_404(Clinician, pk=request.POST["clinician_id"])
    day = date.fromisoformat(request.POST["day"])
    part = request.POST["part"]
    st = get_object_or_404(SessionType, pk=request.POST["session_type_id"])
    site = Site.objects.filter(pk=request.POST.get("site_id") or None).first()
    if not st.is_eligible(clinician) and not request.POST.get("confirm"):
        return render(request, "rota/_cell_form.html", _cell_context(
            clinician, day, part,
            warning=f"{clinician.name} is not usually eligible for {st.name}. "
                    "Save again to override.",
            confirm=True, selected_type=st.id,
        ))
    if request.POST.get("full_day"):
        entries_svc.assign_full_day(request.user, clinician, day, st,
                                    manually_set=True)
    else:
        entries_svc.assign(request.user, clinician, day, part, st, site=site,
                           note=request.POST.get("note", ""), manually_set=True)
    return _refresh()


@admin_required
@require_POST
def clear(request):
    clinician = get_object_or_404(Clinician, pk=request.POST["clinician_id"])
    entries_svc.clear(request.user, clinician,
                      date.fromisoformat(request.POST["day"]),
                      request.POST["part"])
    return _refresh()


@admin_required
@require_POST
def publish(request):
    entries_svc.publish_range(request.user,
                              date.fromisoformat(request.POST["start"]),
                              date.fromisoformat(request.POST["end"]))
    return _refresh()


@admin_required
def daynote_form(request, day):
    d = date.fromisoformat(day)
    note = DayNote.objects.filter(day=d).first()
    return render(request, "rota/_daynote_form.html", {"day": d, "note": note})


@admin_required
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
        "session_types": SessionType.objects.all(),
        "locums": Clinician.objects.filter(active=True,
                                           group__is_locum_group=True),
        "statuses": LocumRequirement.Status.choices,
    }


@admin_required
def locum_new(request):
    return render(request, "rota/_locum_form.html", _locum_form_context(
        day=date.fromisoformat(request.GET["day"]), part=request.GET["part"]))


@admin_required
def locum_form(request, pk):
    req = get_object_or_404(LocumRequirement, pk=pk)
    return render(request, "rota/_locum_form.html", _locum_form_context(req=req))


@admin_required
@require_POST
def locum_save(request):
    st = get_object_or_404(SessionType, pk=request.POST["session_type_id"])
    clinician = Clinician.objects.filter(
        pk=request.POST.get("clinician_id") or None).first()
    try:
        locums_svc.save_requirement(
            request.user,
            pk=request.POST.get("pk") or None,
            day=date.fromisoformat(request.POST["day"]),
            part=request.POST["part"],
            session_type=st,
            status=request.POST["status"],
            details=request.POST.get("details", ""),
            clinician=clinician,
        )
    except ValueError as e:
        ctx = _locum_form_context(day=date.fromisoformat(request.POST["day"]),
                                  part=request.POST["part"])
        ctx["warning"] = str(e)
        return render(request, "rota/_locum_form.html", ctx)
    return _refresh()
