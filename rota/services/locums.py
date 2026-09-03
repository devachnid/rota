from django.db import transaction

from rota.models import LocumRequirement
from rota.services import entries


@transaction.atomic
def save_requirement(actor, *, pk=None, day, part, session_type, status,
                     details="", clinician=None, covering=None):
    if covering is not None and covering.group.is_locum_group:
        raise ValueError("Covering must be a clinician outside the locum group.")
    if pk:
        req = LocumRequirement.objects.get(pk=pk)
        if req.status == LocumRequirement.Status.BOOKED and req.rota_entry_id is not None and (
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
    req.covering = covering
    if (status == LocumRequirement.Status.BOOKED
            and (req.status != LocumRequirement.Status.BOOKED
                 or req.rota_entry_id is None)):
        if clinician is None or not clinician.group.is_locum_group:
            raise ValueError("Booking requires a clinician in the locum group.")
        # The note is what the grid cell shows on hover and what lights the
        # note marker, so it says who the locum stands in for.
        note = details
        if covering is not None:
            note = f"Covering {covering.name}. {details}".rstrip()
        entry = entries.assign(
            actor, clinician, day, part, session_type,
            note=note[:200], published=True, manually_set=True,
        )
        req.clinician = clinician
        req.rota_entry = entry
    req.status = status
    req.save()
    return req
