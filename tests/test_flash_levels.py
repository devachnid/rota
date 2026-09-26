"""A message says what happened; its colour must not contradict it.

Every message used to render in the same accent-soft card, so "Swap could
not be applied" arrived in the visual language of "Swap applied". The level
Django already carries is now on the element, and the three grounds come
from the tokens the badges and warnings use.
"""

from pathlib import Path

import pytest
from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from django.template.loader import render_to_string

from rota.models import PracticeSettings

pytestmark = pytest.mark.django_db
CSS = (Path(__file__).resolve().parents[1] / "static" / "css" / "components.css").read_text()


def _rendered(rf, add):
    """base.html with whatever `add(request)` put in the message store."""
    PracticeSettings.load()
    request = rf.get("/me/")
    request.session = {}
    request.user = AnonymousUser()
    request._messages = FallbackStorage(request)
    add(request)
    return render_to_string("base.html", {}, request=request)


def test_an_error_is_not_dressed_as_a_success(rf):
    html = _rendered(rf, lambda r: messages.error(r, "Swap could not be applied."))
    assert 'class="flash flash-error"' in html
    assert "Swap could not be applied." in html


def test_each_level_carries_its_own_class(rf):
    for add, expected in (
        (lambda r: messages.success(r, "Swap applied."), "flash flash-success"),
        (lambda r: messages.warning(r, "Email isn't set up."), "flash flash-warning"),
        (lambda r: messages.info(r, "Nothing to do."), "flash flash-info"),
    ):
        assert f'class="{expected}"' in _rendered(rf, add)


def test_the_nudges_are_not_dressed_as_messages(gp_client):
    """The passkey and install cards are offers, not outcomes: they keep the
    plain .flash and must never pick up a level."""
    PracticeSettings.load()
    html = gp_client.get("/me/").content.decode()
    for nudge in ('id="passkey-nudge"', 'id="install-nudge"'):
        assert nudge in html
    assert "flash-error" not in html and "flash-success" not in html


def test_the_three_grounds_are_the_tokens_the_rest_of_the_app_uses():
    """Error and warning take the same soft grounds as .badge.POSSIBLE and
    .badge.ADVERTISED, so a failure reads the same wherever it appears."""
    for cls, token in (("flash-error", "--danger"),
                       ("flash-warning", "--warning"),
                       ("flash-success", "--ok")):
        rule = CSS[CSS.index(f".flash.{cls}"):]
        rule = rule[:rule.index("}")]
        assert f"var({token}-soft)" in rule, cls
        assert f"var({token})" in rule, f"{cls} needs a rule in its own colour"
