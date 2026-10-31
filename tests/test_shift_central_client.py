"""The Shift Central client: a token with stray whitespace never reaches the wire and never reaches an error."""

import urllib.error
import urllib.request
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


class _Resp:
    """What urlopen returns: a context manager with read()."""

    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _ask(opener, url="https://shifts.example"):
    return ShiftCentralClient(url, "t", opener=opener).leave(date(2027, 1, 1), date(2027, 1, 31))


def test_a_plain_http_url_is_refused_before_any_request_when_debug_is_off(settings):
    settings.DEBUG = False
    sent = []
    with pytest.raises(ShiftCentralError, match="not https"):
        _ask(lambda req: sent.append(req), url="http://shifts.example")
    assert sent == []       # the token never left


def test_a_plain_http_url_is_allowed_in_debug_only(settings):
    settings.DEBUG = True
    assert _ask(lambda req: _Resp(b'{"leave": []}'), url="http://127.0.0.1:8000") == {"leave": []}


def test_the_client_never_follows_a_redirect():
    handler = sc_client._RefuseRedirects()
    req = urllib.request.Request("https://shifts.example/api/v1/leave", headers={"Authorization": "Bearer t"})
    assert handler.redirect_request(req, None, 302, "Found", {}, "http://elsewhere.example/") is None

    def redirected(req):
        raise urllib.error.HTTPError(req.full_url, 302, "Found", {}, None)
    with pytest.raises(ShiftCentralError, match="returned 302"):
        _ask(redirected)


def test_a_body_that_is_not_json_is_an_error_that_quotes_nothing():
    with pytest.raises(ShiftCentralError) as caught:
        _ask(lambda req: _Resp(b"<html>secret page</html>"))
    assert str(caught.value) == "Shift Central returned a non-JSON body for leave"


@pytest.mark.parametrize("body", [b"{}", b'{"leave": null}', b'{"leave": {"a": 1}}', b"[]", b'"leave"'])
def test_a_response_without_a_leave_list_is_an_error(body):
    with pytest.raises(ShiftCentralError, match="no 'leave' list"):
        _ask(lambda req: _Resp(body))
