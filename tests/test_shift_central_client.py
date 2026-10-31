"""The Shift Central client: a token with stray whitespace never reaches the wire and never reaches an error."""

from datetime import date

import pytest

from rota.services.shift_central import client as sc_client
from rota.services.shift_central.client import ShiftCentralClient, ShiftCentralError


@pytest.mark.parametrize("token", ["abc\ndef", "abc\r\ndef", "abc def", "abc\tdef", " abc", "abc\n"])
def test_a_token_holding_whitespace_is_treated_as_unconfigured(settings, token):
    settings.SHIFT_CENTRAL_URL, settings.SHIFT_CENTRAL_TOKEN = "https://shifts.example", token
    assert sc_client.from_settings() is None


def test_a_clean_token_gives_a_client(settings):
    settings.SHIFT_CENTRAL_URL, settings.SHIFT_CENTRAL_TOKEN = "https://shifts.example", "abc123"
    assert sc_client.from_settings() is not None


def test_a_malformed_token_raises_without_naming_the_token(settings):
    settings.DEBUG = True
    secret = "s3cr3t-part\nX-Injected: yes"
    c = ShiftCentralClient("http://127.0.0.1:9", secret, opener=None, timeout=1)
    with pytest.raises(ShiftCentralError) as caught:
        c.leave(date(2027, 1, 1), date(2027, 1, 31))
    assert str(caught.value) == "Shift Central token is malformed"
    assert "s3cr3t" not in str(caught.value) and caught.value.__cause__ is None


def test_a_value_error_from_the_transport_is_malformed_not_a_leak():
    def opener(req):
        raise ValueError("Invalid header value b'Bearer s3cr3t\\nx'")
    c = ShiftCentralClient("https://shifts.example", "t", opener=opener)
    with pytest.raises(ShiftCentralError) as caught:
        c.leave(date(2027, 1, 1), date(2027, 1, 31))
    assert str(caught.value) == "Shift Central token is malformed" and "s3cr3t" not in str(caught.value)
