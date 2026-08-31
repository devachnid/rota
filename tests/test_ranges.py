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
    """str.isdigit() is true for all of these. Most of them (the superscripts
    and subscripts) then make int() raise; isascii() rejects those before
    int() ever sees them. "٣" (Arabic-Indic three) is different: it is
    Unicode category Nd, so int("٣") succeeds and silently returns 3 — a
    number the admin never typed. isascii() rejects that case too, on the
    same non-ASCII grounds, closing off both failure shapes at once."""
    with pytest.raises(ValidationError):
        parse_int_list(unicode_digit)


@pytest.mark.parametrize("value", [
    "9" * 5000,                    # over CPython's 4300-digit int() limit
    f"{'9' * 5000}-{'9' * 5000}",  # the same, in the range branch
])
def test_absurdly_long_digit_strings_raise_validation_errors(value):
    """isascii() and isdigit() are both true here, but int() still refuses.
    The module's guarantee is that it raises nothing but ValidationError —
    a guarantee is worth having only if it has no exceptions."""
    with pytest.raises(ValidationError):
        parse_int_list(value)
    with pytest.raises(ValidationError):
        validate_int_list(value, 1, 12, "months")


def test_a_range_wider_than_the_cap_is_refused_before_it_is_built():
    """The bounds check in validate_int_list runs after parse_int_list has
    already materialised the list, so it cannot help. "1-99999999" is ten
    characters and one typo away from a real value."""
    with pytest.raises(ValidationError):
        parse_int_list("1-99999999")
    with pytest.raises(ValidationError):
        validate_int_list("1-99999999", 1, 12, "months")


def test_the_cap_does_not_refuse_anything_a_real_field_would_hold():
    """Months are 1-12 and weekdays 0-6; the cap must be nowhere near them."""
    assert parse_int_list("1-12") == list(range(1, 13))
    assert parse_int_list("0-6") == list(range(0, 7))


def test_the_total_output_is_bounded_not_just_each_range():
    """Per-segment caps compose: fifty thousand legal segments cost as much as
    one illegal one. Not reachable through today's max_length-limited fields,
    but this parser deliberately does not know about its callers."""
    with pytest.raises(ValidationError):
        parse_int_list(",".join(["1-1000"] * 50000))


def test_the_total_bound_covers_plain_numbers_as_well_as_ranges():
    """Nothing about composing is particular to the range branch — a list of
    single numbers grows the same list, one element per comma."""
    with pytest.raises(ValidationError):
        parse_int_list(",".join(["1"] * 200000))


def test_the_total_refusal_reads_differently_from_the_per_range_refusal():
    """Two limits, so two messages: an admin who hits the total one needs to
    know that shortening a single range may not be enough to clear it."""
    with pytest.raises(ValidationError) as total:
        parse_int_list(",".join(["1-1000"] * 50000))
    with pytest.raises(ValidationError) as one_range:
        parse_int_list("1-99999999")
    assert "in total" in str(total.value)
    assert "10000" in str(total.value)
    assert "single range" in str(one_range.value)


def test_ordinary_multi_segment_values_are_unaffected():
    assert parse_int_list("1-3,10-12") == [1, 2, 3, 10, 11, 12]
    assert parse_int_list("1,2,3,4,5,6,7,8,9,10,11,12") == list(range(1, 13))


def test_a_refusal_message_can_always_be_rendered():
    """int() accepts 4300 digits and str() refuses 4301, so the span of
    "0-<4300 nines>" is one digit longer than either of its bounds and one
    digit too long to write down. Django formats a ValidationError's message
    lazily, so naming that span in the refusal put a raw ValueError back on
    the escape path — the very failure class rounds 1 and 2 closed, this time
    thrown by the refusal rather than by the parse."""
    value = "0-" + "9" * 4300
    with pytest.raises(ValidationError) as exc:
        parse_int_list(value)
    assert str(exc.value)  # rendering the message must not raise either
    with pytest.raises(ValidationError):
        validate_int_list(value, 1, 12, "months")


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
