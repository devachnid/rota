from django.db import transaction

from rota.models import LocumRequirement
from rota.services import entries


@transaction.atomic
def save_requirement(actor, *, pk=None, day, part, session_type, status,
                     details="", clinician=None):
    if pk:
        req = LocumRequirement.objects.get(pk=pk)
        if req.status == LocumRequirement.Status.BOOKED and (
            status != LocumRequirement.Status.BOOKED
            or (clinician is not None and clinician != req.clinician)
            or day != req.day
            or part != req.part
            or session_type != req.session_type
        ):
            raise ValueError(
                "Already booked — clear the booked session on the grid and "
                "start a new requirement instead."
            )
    else:
        req = LocumRequirement(day=day, part=part)
    req.day, req.part = day, part
    req.session_type = session_type
    req.details = details
    if (status == LocumRequirement.Status.BOOKED
            and req.status != LocumRequirement.Status.BOOKED):
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
