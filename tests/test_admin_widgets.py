"""Free-text lists of numbers become checkboxes; the stored string is the
same, so every reader (rota/services/ranges.py) is untouched."""

import pytest
from django import forms

from rota.admin_forms import (MONTHS, WEEKDAYS, IntListCheckboxField,
                              CoverageRuleForm, PracticeSettingsForm)


class WeekdayForm(forms.Form):
    days = IntListCheckboxField(choices=WEEKDAYS)


class OrderedForm(forms.Form):
    days = IntListCheckboxField(choices=WEEKDAYS, ordered=True)


def test_checked_boxes_become_the_stored_string():
    f = WeekdayForm({"days": ["0", "1", "4"]})
    assert f.is_valid(), f.errors
    assert f.cleaned_data["days"] == "0,1,4"


def test_nothing_ticked_is_an_empty_string():
    f = WeekdayForm({})
    assert f.is_valid()
    assert f.cleaned_data["days"] == ""


def test_the_stored_string_pre_ticks_the_boxes():
    f = WeekdayForm(initial={"days": "0,1,2,3,4"})
    html = f.as_p()
    assert html.count("checked") == 5


def test_a_value_outside_the_choices_is_refused():
    assert not WeekdayForm({"days": ["9"]}).is_valid()


def test_an_ordered_field_keeps_the_order_the_user_gave():
    f = OrderedForm({"days": ["3", "1"], "days_order_3": "1", "days_order_1": "2"})
    assert f.is_valid(), f.errors
    assert f.cleaned_data["days"] == "3,1"
    f = OrderedForm({"days": ["3", "1"], "days_order_3": "2", "days_order_1": "1"})
    assert f.is_valid()
    assert f.cleaned_data["days"] == "1,3"


def test_has_changed_compares_against_the_stored_string():
    f = WeekdayForm({"days": ["0", "1"]}, initial={"days": "0,1"})
    assert not f.has_changed()
    f = WeekdayForm({"days": ["0"]}, initial={"days": "0,1"})
    assert f.has_changed()


@pytest.mark.django_db
def test_the_coverage_rule_form_round_trips_through_the_model():
    from rota.models import CoverageRule
    from tests.factories import make_session_type
    st = make_session_type("Duty")
    f = CoverageRuleForm({"session_type": st.pk, "unit": "SESSION", "frequency": "WEEK",
                          "count": 2, "priority": 5, "parts": "BOTH",
                          "weekdays": ["1", "3"], "months": [],
                          "preferred_weekdays": ["3", "1"],
                          "preferred_weekdays_order_3": "1", "preferred_weekdays_order_1": "2"})
    assert f.is_valid(), f.errors
    rule = f.save()
    rule.refresh_from_db()
    assert (rule.weekdays, rule.months, rule.preferred_weekdays) == ("1,3", "", "3,1")
    assert rule.preferred_weekday_list() == [3, 1]


@pytest.mark.django_db
def test_the_settings_form_accepts_no_days_as_today_does():
    from rota.models import PracticeSettings
    s = PracticeSettings.load()
    f = PracticeSettingsForm({"min_clinical_per_session": 2, "open_weekdays": []}, instance=s)
    assert f.is_valid(), f.errors
    assert f.cleaned_data["open_weekdays"] == ""


def test_month_choices_are_january_to_december():
    assert MONTHS[0] == (1, "January") and MONTHS[-1] == (12, "December")
