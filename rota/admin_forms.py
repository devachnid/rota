"""Form fields for the admin that present a stored list of integers as
checkboxes and store it back as the same comma-joined string.

PracticeSettings.open_weekdays and CoverageRule.weekdays / months /
preferred_weekdays are CharFields like "0,1,2,3,4", parsed by
rota/services/ranges.py. Nothing about storage changes here; the commonest
setup mistake — a stray comma — simply cannot be made from a checkbox.
"""

from django import forms

from rota.models import CoverageRule, PracticeSettings

WEEKDAYS = [(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"),
            (4, "Friday"), (5, "Saturday"), (6, "Sunday")]
MONTHS = [(1, "January"), (2, "February"), (3, "March"), (4, "April"),
          (5, "May"), (6, "June"), (7, "July"), (8, "August"),
          (9, "September"), (10, "October"), (11, "November"), (12, "December")]


class OrderedCheckboxSelect(forms.CheckboxSelectMultiple):
    """Checkboxes plus a small order number beside each, for the one field
    whose stored order is significant (preferred_weekdays: "3,1" means
    Thursday first, then Tuesday). Submits `<name>` for the ticks and
    `<name>_order_<value>` for the numbers; the field sorts by number."""
    # Lives under rota/templates/, not templates/ at the project root:
    # Django's default form renderer resolves a widget template by
    # searching each installed app's own template directory, not
    # settings.TEMPLATES["DIRS"].
    template_name = "admin/rota/widgets/ordered_checkboxes.html"

    def value_from_datadict(self, data, files, name):
        ticked = data.getlist(name) if hasattr(data, "getlist") else data.get(name, [])
        def order(v):
            raw = data.get(f"{name}_order_{v}", "")
            try:
                return int(raw)
            except (TypeError, ValueError):
                return 10 ** 6
        return sorted(ticked, key=order)

    def get_context(self, name, value, attrs):
        current = [str(v) for v in (value or [])]
        self._order = {v: i + 1 for i, v in enumerate(current)}
        return super().get_context(name, value, attrs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        option["order"] = getattr(self, "_order", {}).get(str(value), "")
        return option


class IntListCheckboxField(forms.MultipleChoiceField):
    def __init__(self, *, choices, ordered=False, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("widget", OrderedCheckboxSelect if ordered
                          else forms.CheckboxSelectMultiple)
        super().__init__(choices=[(str(v), label) for v, label in choices], **kwargs)

    @staticmethod
    def _split(value):
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return list(value or [])

    def prepare_value(self, value):
        return self._split(value)

    def clean(self, value):
        return ",".join(super().clean(value))

    def has_changed(self, initial, data):
        return self.clean(data) != ",".join(self._split(initial))


class CoverageRuleForm(forms.ModelForm):
    weekdays = IntListCheckboxField(choices=WEEKDAYS, label="Weekdays")
    months = IntListCheckboxField(choices=MONTHS, label="Months",
                                  help_text="None ticked means all year.")
    preferred_weekdays = IntListCheckboxField(
        choices=WEEKDAYS, ordered=True, label="Preferred weekdays",
        help_text="For per-week and per-month rules: tick the days to try "
                  "first, numbered in order of preference.")

    class Meta:
        model = CoverageRule
        fields = "__all__"


class PracticeSettingsForm(forms.ModelForm):
    open_weekdays = IntListCheckboxField(choices=WEEKDAYS, label="Open weekdays")

    class Meta:
        model = PracticeSettings
        fields = "__all__"
