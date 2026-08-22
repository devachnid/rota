from datetime import date

from rota.models import Clinician, ClinicianGroup, SessionType, Site

MON = date(2026, 7, 20)  # a Monday


def make_group(name="Salaried", **kw):
    kw.setdefault("display_order", 10)
    return ClinicianGroup.objects.create(name=name, **kw)


def make_clinician(name="Alice Adams", group=None, user=None, **kw):
    if group is None:
        group = ClinicianGroup.objects.filter(name="Salaried", is_locum_group=False).first() or make_group()
    kw.setdefault("initials", "".join(w[0] for w in name.split()).upper())
    return Clinician.objects.create(name=name, group=group, user=user, **kw)


def make_session_type(name="Routine", code=None, **kw):
    kw.setdefault("category", SessionType.Category.CLINICAL)
    kw.setdefault("colour", "#8ecae6")
    obj, _ = SessionType.objects.get_or_create(
        name=name, defaults={"code": (code or name[:4].upper()), **kw}
    )
    return obj


def make_site(name="Main Surgery"):
    return Site.objects.create(name=name)


def make_pattern(clinician, weekdays=(0, 1, 2, 3, 4), parts=("AM", "PM"),
                 works=True, effective_from=date(2020, 1, 1)):
    from rota.models import PatternSlot
    return [
        PatternSlot.objects.create(
            clinician=clinician, weekday=w, part=p, works=works,
            effective_from=effective_from,
        )
        for w in weekdays for p in parts
    ]


def make_entry(clinician, day=MON, part="AM", session_type=None, **kw):
    from rota.models import RotaEntry
    kw.setdefault("is_published", True)
    kw.setdefault("manually_set", True)
    return RotaEntry.objects.create(
        clinician=clinician, day=day, part=part,
        session_type=session_type or make_session_type(), **kw,
    )


def make_trainee(clinician=None, stage="ST2", wte=100, trainer=None,
                 start=MON, end=None):
    from datetime import timedelta
    from rota.models import TraineeProfile
    clinician = clinician or make_clinician("Terry Trainee")
    return TraineeProfile.objects.create(
        clinician=clinician, stage=stage, wte_percent=wte, trainer=trainer,
        placement_start=start, placement_end=end or (start + timedelta(days=364)),
    )


def make_commitment(clinician, session_type=None, weekday=0, part="AM", **kw):
    from rota.models import RecurringCommitment
    kw.setdefault("active_from", date(2020, 1, 6))  # a Monday
    return RecurringCommitment.objects.create(
        clinician=clinician, session_type=session_type or make_session_type(),
        weekday=weekday, part=part, **kw,
    )
