import uuid

from django.db import transaction

from rota.models import RotaEntry, RotaEntryLog


def _log(actor, day, part, clinician_name, action, detail=""):
    RotaEntryLog.objects.create(
        day=day, part=part, clinician_name=clinician_name,
        actor=actor, action=action, detail=detail,
    )


def _split_pair(entry):
    if entry.allocation_group:
        RotaEntry.objects.filter(allocation_group=entry.allocation_group).update(
            allocation_group=None
        )
        entry.allocation_group = None


@transaction.atomic
def assign(actor, clinician, day, part, session_type, *, site=None, note="",
           published=False, manually_set=True, fill_reason=""):
    existing = RotaEntry.objects.filter(day=day, part=part, clinician=clinician).first()
    if existing:
        _split_pair(existing)
        detail = f"{existing.session_type.code} -> {session_type.code}"
        existing.session_type = session_type
        existing.site = site
        existing.note = note
        existing.is_published = existing.is_published or published
        existing.manually_set = manually_set
        existing.fill_reason = fill_reason
        existing.save()
        _log(actor, day, part, clinician.name, "changed", detail)
        return existing
    entry = RotaEntry.objects.create(
        day=day, part=part, clinician=clinician, session_type=session_type,
        site=site, note=note, is_published=published,
        manually_set=manually_set, fill_reason=fill_reason,
    )
    _log(actor, day, part, clinician.name, "created", session_type.code)
    return entry


@transaction.atomic
def assign_full_day(actor, clinician, day, session_type, *, published=False,
                    manually_set=True, fill_reason=""):
    group = uuid.uuid4()
    am = assign(actor, clinician, day, "AM", session_type, published=published,
                manually_set=manually_set, fill_reason=fill_reason)
    pm = assign(actor, clinician, day, "PM", session_type, published=published,
                manually_set=manually_set, fill_reason=fill_reason)
    RotaEntry.objects.filter(pk__in=[am.pk, pm.pk]).update(allocation_group=group)
    am.refresh_from_db()
    pm.refresh_from_db()
    return am, pm


@transaction.atomic
def clear(actor, clinician, day, part):
    entry = RotaEntry.objects.filter(day=day, part=part, clinician=clinician).first()
    if not entry:
        return
    _split_pair(entry)
    detail = entry.session_type.code
    entry.delete()
    _log(actor, day, part, clinician.name, "cleared", detail)


@transaction.atomic
def publish_range(actor, start, end):
    n = RotaEntry.objects.filter(
        day__range=(start, end), is_published=False
    ).update(is_published=True)
    _log(actor, start, "", "", "published", f"{start}..{end} ({n} entries)")
    return n
