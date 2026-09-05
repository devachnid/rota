import re

from django import forms

from .models import Feedback

VIEWPORT = re.compile(r"^\d{1,5}x\d{1,5}$")


class FeedbackForm(forms.Form):
    kind = forms.ChoiceField(choices=Feedback.Kind.choices)
    message = forms.CharField(
        max_length=2000, strip=True,
        error_messages={"required": "Say a little about it first."})
    # Filled by an hx-vals expression on the form; anything odd is dropped,
    # never rejected — a report with no viewport is still a report. No
    # max_length here: a field-level limit fails validation before
    # clean_viewport runs, and the template shows no error for this field,
    # so the whole report would be refused silently. The regex below is the
    # only gate, and it caps the value at 11 characters (the column is 20).
    viewport = forms.CharField(required=False)

    def clean_viewport(self):
        value = self.cleaned_data.get("viewport", "")
        return value if VIEWPORT.match(value) else ""
