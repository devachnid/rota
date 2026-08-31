"""The flag that decides which session types head the day view."""

import pytest

from rota.models import SessionType
from tests.factories import make_session_type

pytestmark = pytest.mark.django_db


def test_types_are_not_pinned_by_default():
    t = make_session_type("Routine", code="ROUT")
    assert t.pin_on_day_view is False


def test_a_type_can_be_pinned_and_found_by_query():
    duty = make_session_type("Duty", code="DUTY", pin_on_day_view=True)
    make_session_type("Routine", code="ROUT")
    assert list(SessionType.objects.filter(pin_on_day_view=True)) == [duty]
