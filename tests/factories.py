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
