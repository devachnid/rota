from django.db import transaction

from rota.models import LocumRequirement
from rota.services import entries


@transaction.atomic
def save_requirement(actor, *, pk=None, day, part, session_type, status,
                     details="", clinician=None):
    if pk:
        req = LocumRequirement.objects.get(pk=pk)
    else:
        req = LocumRequirement(day=day, part=part)
    req.day, req.part = day, part
    req.session_type = session_type
    req.details = details
    if status == LocumRequirement.Status.BOOKED:
        if clinician is None or not clinician.group.is_locum_group:
            raise ValueError("Booking requires a clinician in the locum group.")
        entry = entries.assign(
            actor, clinician, day, part, session_type,
            note=details[:200], published=True, manually_set=True,
        )
        req.clinician = clinician
        req.rota_entry = entry
    req.status = status
    req.save()
    return req
