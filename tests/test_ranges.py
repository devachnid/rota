"""Comma-and-range integer lists, as typed into coverage rules.

`1-6,9-12` raised `invalid literal for int() with base 10: '1-6'` from inside
a fill run, because the parse was `int(x) for x in value.split(",")` with no
validation anywhere. The failure landed on whoever ran the fill rather than on
whoever typed the value.
"""

import pytest
from django.core.exceptions import ValidationError

from rota.services.ranges import parse_int_list, validate_int_list


@pytest.mark.parametrize("value,expected", [
    ("", []),
    ("3", [3]),
    ("1,2,3", [1, 2, 3]),
    ("1-6", [1, 2, 3, 4, 5, 6]),
    ("1-6,9-12", [1, 2, 3, 4, 5, 6, 9, 10, 11, 12]),
    ("10,1-3", [10, 1, 2, 3]),          # order is preserved, not sorted
    (" 1 - 3 , 5 ", [1, 2, 3, 5]),      # whitespace tolerated
    ("4-4", [4]),                        # a range of one
    ("0,1,2,3,4", [0, 1, 2, 3, 4]),      # weekdays are zero-based
])
def test_parse_int_list(value, expected):
    assert parse_int_list(value) == expected


@pytest.mark.parametrize("bad", ["x", "1-", "-3", "1-2-3", "1,,2", "1..3", "1-x"])
def test_parse_rejects_malformed_input(bad):
    with pytest.raises(ValidationError):
        parse_int_list(bad)


@pytest.mark.parametrize("unicode_digit", ["²", "⁶-9", "1-³", "٣"])
def test_unicode_digits_are_rejected_as_validation_errors_not_value_errors(
    unicode_digit
):
    """str.isdigit() is true for these; int() rejects them. Gating on isdigit()
    alone let a raw ValueError escape — the same failure this module exists to
    prevent, from a rarer input."""
    with pytest.raises(ValidationError):
        parse_int_list(unicode_digit)


def test_a_descending_range_is_rejected_rather_than_silently_empty():
    """range(6, 1) is empty, so `6-1` would quietly mean 'never applies' —
    a rule that silently does nothing is worse than one that refuses."""
    with pytest.raises(ValidationError):
        parse_int_list("6-1")


@pytest.mark.parametrize("value", ["1-12", "1,12", "6"])
def test_validate_accepts_in_range_months(value):
    validate_int_list(value, 1, 12, "months")


@pytest.mark.parametrize("value", ["0", "13", "1-13", "0-5"])
def test_validate_rejects_out_of_range_months(value):
    with pytest.raises(ValidationError):
        validate_int_list(value, 1, 12, "months")


def test_validation_message_names_the_field_and_the_bad_value():
    with pytest.raises(ValidationError) as exc:
        validate_int_list("13", 1, 12, "months")
    message = str(exc.value)
    assert "months" in message
    assert "13" in message


@pytest.mark.django_db
def test_a_coverage_rule_with_a_month_range_applies_on_the_right_days():
    from datetime import date
    from rota.models import CoverageRule
    from tests.factories import make_session_type

    rule = CoverageRule(session_type=make_session_type("Winter", code="WIN"),
                        months="1-3,10-12", weekdays="0-4")
    assert rule.applies_on(date(2026, 1, 5)) is True     # Monday in January
    assert rule.applies_on(date(2026, 11, 4)) is True    # Wednesday in November
    assert rule.applies_on(date(2026, 6, 3)) is False    # Wednesday in June
    assert rule.applies_on(date(2026, 1, 4)) is False    # a Sunday


@pytest.mark.django_db
def test_a_bad_month_range_is_refused_at_save_not_at_fill_time():
    from rota.models import CoverageRule
    from tests.factories import make_session_type

    rule = CoverageRule(session_type=make_session_type("Bad", code="BAD"),
                        months="1-13")
    with pytest.raises(ValidationError):
        rule.full_clean()
