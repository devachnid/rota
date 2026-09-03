"""The overlay tables the sync writes and everything else reads."""

from datetime import date

import pytest
from django.db import IntegrityError

from rota.models import BreatheAbsence, BreatheLeaveMapping, Clinician, SessionType
from tests.factories import make_clinician, make_session_type

pytestmark = pytest.mark.django_db

MON = date(2026, 9, 14)


def _absence(c, **kw):
    kw.setdefault("start_date", MON); kw.setdefault("end_date", MON)
    kw.setdefault("kind", BreatheAbsence.Kind.HOLIDAY)
    kw.setdefault("source_ids", "1")
    return BreatheAbsence.objects.create(clinician=c, **kw)


def test_the_content_key_is_unique_per_clinician():
    """Two endpoints returning the same leave collide here, not in a loop."""
    c = make_clinician()
    _absence(c)
    with pytest.raises(IntegrityError):
        _absence(c, source_ids="2")


def test_different_half_day_flags_are_different_rows():
    c = make_clinician()
    _absence(c)
    _absence(c, half_start=True, half_start_am_pm="PM", source_ids="2")
    assert BreatheAbsence.objects.count() == 2


def test_span_exposes_the_half_day_fields():
    c = make_clinician()
    a = _absence(c, end_date=date(2026, 9, 16), half_end=True, half_end_am_pm="AM")
    assert a.span.half_end_am_pm == "AM" and a.span.end_date == date(2026, 9, 16)


def test_mapping_resolves_exact_reason_then_kind_default():
    al = make_session_type("Annual leave", code="AL", category="ABSENCE")
    mat = make_session_type("Maternity", code="MAT", category="ABSENCE")
    oth = make_session_type("Other leave", code="OTH", category="ABSENCE")
    BreatheLeaveMapping.objects.all().delete()
    BreatheLeaveMapping.objects.create(kind="holiday", reason="", session_type=al)
    BreatheLeaveMapping.objects.create(kind="other", reason="", session_type=oth)
    BreatheLeaveMapping.objects.create(kind="other", reason="Maternity", session_type=mat)
    m = BreatheLeaveMapping.as_dict()
    assert m[("holiday", "")] == al
    assert m[("other", "Maternity")] == mat
    assert m[("other", "")] == oth
    assert ("other", "Paternity") not in m, "no exact row; callers fall back to the kind default"


def test_the_migration_seeded_three_types_and_three_defaults():
    """The seed is the whole configuration a fresh install needs."""
    kinds = {m.kind for m in BreatheLeaveMapping.objects.filter(reason="")}
    assert kinds == {"holiday", "other", "sickness"}
    for code in ("AL", "SICK", "OTH"):
        t = SessionType.objects.get(code=code)
        assert t.category == SessionType.Category.ABSENCE


def test_mapping_session_type_must_be_an_absence_type():
    rout = make_session_type("Routine", code="ROUT")
    m = BreatheLeaveMapping(kind="holiday", reason="x", session_type=rout)
    with pytest.raises(Exception):
        m.full_clean()


def test_breathe_employee_id_is_unique_but_optional():
    a = make_clinician("A", breathe_employee_id=100)
    make_clinician("B")  # unlinked is fine
    make_clinician("C")  # two unlinked are fine (NULLs do not collide)
    with pytest.raises(IntegrityError):
        make_clinician("D", breathe_employee_id=100)
