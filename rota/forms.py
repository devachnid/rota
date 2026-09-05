"""Forms for the pages GPs use themselves. The admin has its own."""

from django import forms

from rota.models import RotaEntry


class SwapForm(forms.Form):
    """Propose a swap: one of my upcoming published sessions for one of a
    colleague's.

    The two querysets passed in are the only sessions the form accepts, so
    an id from outside them — someone else's session, a colleague with no
    login, a day already gone — fails validation and is reported beside the
    field, rather than reaching the view as a 404 or a bare "Bad request".
    The field names are the POST keys the page has always sent.
    """

    my_entry_id = forms.ModelChoiceField(
        queryset=RotaEntry.objects.none(),
        error_messages={
            "required": "Choose one of your sessions.",
            "invalid_choice": "That isn't one of your upcoming published "
                              "sessions — choose one from the list.",
        },
    )
    their_entry_id = forms.ModelChoiceField(
        queryset=RotaEntry.objects.none(),
        error_messages={
            "required": "Choose a colleague's session.",
            "invalid_choice": "That session can't be swapped — choose one "
                              "from the list.",
        },
    )
    message = forms.CharField(required=False, strip=True, max_length=500)

    def __init__(self, mine, theirs, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["my_entry_id"].queryset = mine
        self.fields["their_entry_id"].queryset = theirs
