from datetime import timedelta

from django.db import transaction

from rota.models import Part, PatternSlot


def current_pattern(clinician, as_of):
    rows = PatternSlot.objects.filter(
        clinician=clinician, effective_from__lte=as_of
    ).order_by("effective_from")
    pattern = {}
    for row in rows:
        pattern[(row.weekday, row.part)] = row.works
    return pattern


@transaction.atomic
def bulk_set_pattern(clinician, effective_from, desired):
    existing_at_date = {
        (row.weekday, row.part): row
        for row in PatternSlot.objects.filter(
            clinician=clinician, effective_from=effective_from
        )
    }
    prior = current_pattern(clinician, effective_from - timedelta(days=1))

    changed = 0
    for weekday in range(7):
        for part in Part.values:
            want = bool(desired.get((weekday, part), False))
            exact = existing_at_date.get((weekday, part))
            if exact is not None:
                if exact.works != want:
                    exact.works = want
                    exact.save(update_fields=["works"])
                    changed += 1
                continue
            if want != prior.get((weekday, part), False):
                PatternSlot.objects.create(
                    clinician=clinician, weekday=weekday, part=part,
                    effective_from=effective_from, works=want,
                )
                changed += 1
    return changed
