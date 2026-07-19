from rota.models import Clinician, Part, PatternSlot


def _current_slot(clinician, weekday, part, as_of):
    return (
        PatternSlot.objects.filter(
            clinician=clinician, weekday=weekday, part=part, effective_from__lte=as_of
        )
        .order_by("-effective_from")
        .first()
    )


def works_on(clinician, day, part):
    slot = _current_slot(clinician, day.weekday(), part, day)
    return bool(slot and slot.works)


def weekly_sessions(clinician, as_of):
    return sum(
        1
        for weekday in range(7)
        for part in Part.values
        if (s := _current_slot(clinician, weekday, part, as_of)) and s.works
    )


def available_clinicians(day, part):
    return [c for c in Clinician.objects.filter(active=True) if works_on(c, day, part)]
