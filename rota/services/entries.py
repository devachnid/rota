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


def _split_companion(entry):
    if entry.companion_group:
        RotaEntry.objects.filter(companion_group=entry.companion_group).update(
            companion_group=None
        )
        entry.companion_group = None


@transaction.atomic
def assign(actor, clinician, day, part, session_type, *, site=None, note="",
           published=False, manually_set=True, fill_reason=""):
    existing = RotaEntry.objects.filter(day=day, part=part, clinician=clinician).first()
    if existing:
        _split_pair(existing)
        _split_companion(existing)
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
def assign_full_day(actor, clinician, day, session_type, *, site=None, note="",
                    published=False, manually_set=True, fill_reason=""):
    group = uuid.uuid4()
    am = assign(actor, clinician, day, "AM", session_type, site=site, note=note,
                published=published, manually_set=manually_set, fill_reason=fill_reason)
    pm = assign(actor, clinician, day, "PM", session_type, site=site, note=note,
                published=published, manually_set=manually_set, fill_reason=fill_reason)
    RotaEntry.objects.filter(pk__in=[am.pk, pm.pk]).update(allocation_group=group)
    am.refresh_from_db()
    pm.refresh_from_db()
    return am, pm


@transaction.atomic
def assign_pair(actor, day, part, first, second, session_type, *, site=None,
                published=False, manually_set=True, fill_reason=""):
    group = uuid.uuid4()
    e1 = assign(actor, first, day, part, session_type, site=site,
                published=published, manually_set=manually_set,
                fill_reason=fill_reason)
    e2 = assign(actor, second, day, part, session_type, site=site,
                published=published, manually_set=manually_set,
                fill_reason=fill_reason)
    RotaEntry.objects.filter(pk__in=[e1.pk, e2.pk]).update(companion_group=group)
    e1.refresh_from_db()
    e2.refresh_from_db()
    return e1, e2


@transaction.atomic
def clear(actor, clinician, day, part):
    entry = RotaEntry.objects.filter(day=day, part=part, clinician=clinician).first()
    if not entry:
        return
    if entry.companion_group:
        partner = RotaEntry.objects.filter(
            companion_group=entry.companion_group
        ).exclude(pk=entry.pk).select_related("clinician", "session_type").first()
        if partner:
            p_day, p_part, p_name = partner.day, partner.part, partner.clinician.name
            p_detail = partner.session_type.code
            partner.delete()
            _log(actor, p_day, p_part, p_name, "cleared", p_detail)
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
