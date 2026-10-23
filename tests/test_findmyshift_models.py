"""The overlay tables the sync writes and everything else reads."""

from datetime import date

import pytest
from django.db import IntegrityError

from rota.models import SessionType, TimeOff, TimeOffMapping
from tests.factories import make_clinician, make_session_type

pytestmark = pytest.mark.django_db

MON = date(2026, 9, 14)


def _absence(c, **kw):
    kw.setdefault("start_date", MON); kw.setdefault("end_date", MON)
    kw.setdefault("reason", "Holiday")
    kw.setdefault("source_ids", "1")
    return TimeOff.objects.create(clinician=c, **kw)


def test_the_content_key_is_unique_per_clinician():
    """Two records covering the same parts collide here, not in a loop."""
    c = make_clinician()
    _absence(c)
    with pytest.raises(IntegrityError):
        _absence(c, source_ids="2")


def test_different_half_day_flags_are_different_rows():
    c = make_clinician()
    _absence(c)
    _absence(c, half_start=True, half_start_am_pm="PM", source_ids="2")
    assert TimeOff.objects.count() == 2


def test_span_exposes_the_half_day_fields():
    c = make_clinician()
    a = _absence(c, end_date=date(2026, 9, 16), half_end=True, half_end_am_pm="AM")
    assert a.span.half_end_am_pm == "AM" and a.span.end_date == date(2026, 9, 16)


def test_mapping_resolves_exact_reason_then_default():
    al = make_session_type("Annual leave", code="AL", category="ABSENCE")
    mat = make_session_type("Maternity", code="MAT", category="ABSENCE")
    oth = make_session_type("Other leave", code="OTH", category="ABSENCE")
    TimeOffMapping.objects.all().delete()
    TimeOffMapping.objects.create(reason="", session_type=oth)
    TimeOffMapping.objects.create(reason="Holiday", session_type=al)
    TimeOffMapping.objects.create(reason="Maternity", session_type=mat)
    m = TimeOffMapping.as_dict()
    assert m["Holiday"] == al
    assert m["Maternity"] == mat
    assert m[""] == oth
    assert "Paternity" not in m, "no exact row; callers fall back to the default"


def test_the_migration_seeded_three_types_and_the_common_reasons():
    """The seed is the whole configuration a fresh install needs: a
    default, and the reason names an account is likely to use."""
    m = {r: t.code for r, t in TimeOffMapping.as_dict().items()}
    assert m[""] == "OTH"
    assert m["Holiday"] == "AL" and m["Annual leave"] == "AL"
    assert m["Sick"] == "SICK" and m["Sickness"] == "SICK"
    for code in ("AL", "SICK", "OTH"):
        t = SessionType.objects.get(code=code)
        assert t.category == SessionType.Category.ABSENCE


def test_mapping_session_type_must_be_an_absence_type():
    rout = make_session_type("Routine", code="ROUT")
    m = TimeOffMapping(reason="x", session_type=rout)
    with pytest.raises(Exception):
        m.full_clean()


def test_findmyshift_staff_id_is_unique_but_optional():
    make_clinician("A", findmyshift_staff_id="S100")
    make_clinician("B")  # unlinked is fine
    make_clinician("C")  # two unlinked are fine (NULLs do not collide)
    with pytest.raises(IntegrityError):
        make_clinician("D", findmyshift_staff_id="S100")


def test_a_blank_reason_is_still_time_off():
    c = make_clinician()
    a = _absence(c, reason="")
    assert "time off" in str(a)
