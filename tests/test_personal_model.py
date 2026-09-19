"""A personal requirement: each named clinician does a session type once
every N weeks, on no fixed day. The model holds the who/what/how-often;
the clock lives in rota/services/personal.py."""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError

from rota.models import PersonalRequirement
from tests.factories import MON, make_clinician, make_requirement, make_session_type

pytestmark = pytest.mark.django_db


def test_str_names_the_type_and_the_interval():
    req = make_requirement(make_session_type("Nursing home round", code="NH"), interval_weeks=6)
    assert str(req) == "Nursing home round every 6 weeks"


def test_defaults():
    req = make_requirement()
    assert req.interval_weeks == 6 and req.part == "EITHER" and req.weekdays == ""
    assert req.parts_for() == ["AM", "PM"] and req.weekday_list() == []


def test_clean_rejects_a_zero_interval():
    req = make_requirement()
    req.interval_weeks = 0
    with pytest.raises(ValidationError) as exc:
        req.clean()
    assert "interval_weeks" in exc.value.message_dict


def test_clean_rejects_a_bad_weekday_list_and_a_backwards_window():
    req = make_requirement()
    req.weekdays = "1,,3"
    with pytest.raises(ValidationError) as exc:
        req.clean()
    assert "weekdays" in exc.value.message_dict
    req.weekdays = "7"
    with pytest.raises(ValidationError):
        req.clean()
    req.weekdays = "1,3"
    req.active_until = req.active_from - timedelta(days=1)
    with pytest.raises(ValidationError) as exc:
        req.clean()
    assert "active_until" in exc.value.message_dict


def test_live_on_and_applies_on():
    req = make_requirement(active_from=MON, active_until=MON + timedelta(days=13),
                           weekdays="1,3")
    assert not req.live_on(MON - timedelta(days=1))
    assert req.live_on(MON) and req.live_on(MON + timedelta(days=13))
    assert not req.live_on(MON + timedelta(days=14))
    assert not req.applies_on(MON)                       # Monday, not ticked
    assert req.applies_on(MON + timedelta(days=1))       # Tuesday
    assert not req.applies_on(MON + timedelta(days=15))  # Tuesday, but after the window
    blank = make_requirement(active_from=MON)
    assert blank.applies_on(MON) and blank.applies_on(MON + timedelta(days=6))


def test_parts_for_a_single_half():
    assert make_requirement(part="PM").parts_for() == ["PM"]


def test_a_stored_weekday_list_that_no_longer_parses_stops_at_deploy():
    from rota.checks import stored_ranges_parse
    req = make_requirement()
    PersonalRequirement.objects.filter(pk=req.pk).update(weekdays="1,,3")
    errors = stored_ranges_parse(None)
    assert len(errors) == 1 and errors[0].id == "rota.E006"
    assert "Personal requirement" in errors[0].msg


def test_clinicians_is_a_many_to_many_in_both_directions():
    a, b = make_clinician("Ann Able"), make_clinician("Bob Baker")
    req = make_requirement(clinicians=[a, b])
    assert set(req.clinicians.all()) == {a, b}
    assert list(a.personal_requirements.all()) == [req]
