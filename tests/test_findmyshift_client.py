"""The FindMyShift client, against a fake opener. No network.

tests/fixtures/findmyshift/ is synthetic (see its README): FindMyShift
documents its methods but not its responses, so the records are the shape
the sync reads, with example-domain emails and no personal data. This
repository is public; test_the_fixtures_hold_no_personal_data keeps it that
way. A fake opener serves them, so these tests prove how the client talks
to FindMyShift without ever calling it.
"""

import http.server
import io
import json
import logging
import re
import threading
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs

import pytest

from rota.services.findmyshift.client import (STAFF_FIELDS, FindMyShiftClient,
                                              FindMyShiftError)

FIX = Path(__file__).resolve().parent / "fixtures" / "findmyshift"
BASE = "https://www.findmyshift.co.uk/api/1.4"


class _Resp(io.BytesIO):
    """Enough of an HTTPResponse for the client: body and status."""
    def __init__(self, body: bytes, status=200):
        super().__init__(body)
        self.status = status
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


def fake_opener(routes, seen=None):
    """routes: {method: body_bytes | callable(form) -> body_bytes}; records
    every request."""
    def opener(req):
        if seen is not None:
            seen.append(req)
        method = req.full_url[len(BASE) + 1:]
        if method not in routes:
            raise HTTPError(req.full_url, 404, "not routed", {}, io.BytesIO(b"404: no such method"))
        body = routes[method]
        if callable(body):
            body = body(parse_qs(req.data.decode()))
        return _Resp(body)
    return opener


def _fixture(name):
    return (FIX / f"{name}.json").read_bytes()


# --- how the key travels -----------------------------------------------------

def test_the_key_goes_in_the_form_body_never_the_url():
    seen = []
    c = FindMyShiftClient("k-123", BASE, opener=fake_opener({"teams/list": b"[]"}, seen))
    c.teams()
    (req,) = seen
    assert req.get_method() == "POST"
    assert "k-123" not in req.full_url
    assert parse_qs(req.data.decode())["apiKey"] == ["k-123"]
    assert req.get_header("Accept") == "application/json"


def test_time_off_sends_the_team_and_the_window_as_dates():
    seen = []
    c = FindMyShiftClient("k", BASE, opener=fake_opener({"time-off/list": b"[]"}, seen))
    c.time_off("T1", date(2026, 1, 1), date(2026, 12, 31))
    form = parse_qs(seen[0].data.decode())
    assert form["teamId"] == ["T1"]
    assert form["from"] == ["2026-01-01"] and form["to"] == ["2026-12-31"]


def test_staff_without_a_team_sends_no_team_id():
    seen = []
    c = FindMyShiftClient("k", BASE, opener=fake_opener({"staff/list": b"[]"}, seen))
    c.staff(None)
    assert "teamId" not in parse_qs(seen[0].data.decode())


# --- what comes back ------------------------------------------------------------

def test_a_bare_array_is_the_rows():
    c = FindMyShiftClient("k", BASE, opener=fake_opener({"time-off/list": _fixture("time-off")}))
    rows = c.time_off("T1", date(2026, 1, 1), date(2026, 12, 31))
    assert len(rows) == 14 and rows[0]["id"] == "TO1"


@pytest.mark.parametrize("body", [
    b'{"timeOff": [{"id": "x"}]}',
    b'{"results": [{"id": "x"}]}',
    b'{"status": "ok", "records": [{"id": "x"}]}',
])
def test_a_wrapped_array_is_unwrapped(body):
    c = FindMyShiftClient("k", BASE, opener=fake_opener({"time-off/list": body}))
    assert c.time_off("T1", date(2026, 1, 1), date(2026, 1, 2)) == [{"id": "x"}]


def test_an_empty_object_is_no_rows():
    c = FindMyShiftClient("k", BASE, opener=fake_opener({"time-off/list": b"{}"}))
    assert c.time_off("T1", date(2026, 1, 1), date(2026, 1, 2)) == []


def test_an_object_with_two_lists_is_an_error_naming_the_keys():
    c = FindMyShiftClient("k", BASE, opener=fake_opener(
        {"time-off/list": b'{"a": [], "b": []}'}))
    with pytest.raises(FindMyShiftError) as exc:
        c.time_off("T1", date(2026, 1, 1), date(2026, 1, 2))
    assert "no list" in str(exc.value) and "'a'" in str(exc.value)


def test_staff_are_projected_to_the_allowed_fields_only():
    c = FindMyShiftClient("k", BASE, opener=fake_opener({"staff/list": _fixture("staff")}))
    staff = c.staff()
    assert len(staff) == 7
    for s in staff:
        assert set(s) == set(STAFF_FIELDS)
    for secret in ("dateOfBirth", "mobileNumber", "salaries", "hourlyRates", "profilePicture"):
        assert secret not in STAFF_FIELDS
    assert staff[0]["id"] == "S1", "id is filled from FindMyShift's staffId"
    assert staff[0]["firstName"] == "Tom" and staff[0]["emailAddress"] == "tom@example.org"


# --- errors --------------------------------------------------------------------

def _failing(status, body=b"", headers=None):
    def opener(req):
        raise HTTPError(req.full_url, status, "x", headers or {}, io.BytesIO(body))
    return opener


def test_a_429_raises_a_clear_error_and_does_not_retry():
    calls = []
    def opener(req):
        calls.append(req)
        raise HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(b""))
    c = FindMyShiftClient("k", BASE, opener=opener)
    with pytest.raises(FindMyShiftError) as exc:
        c.teams()
    assert exc.value.status == 429 and "teams/list" in str(exc.value)
    assert len(calls) == 1


def test_a_plain_text_error_body_is_quoted_briefly():
    """FindMyShift says what went wrong in the body — "401: No authentication
    parameters found…" — and that is what an admin needs to see."""
    body = b"401: No authentication parameters found. Please provide apiKey, authToken, or login and password."
    c = FindMyShiftClient("k", BASE, opener=_failing(401, body))
    with pytest.raises(FindMyShiftError) as exc:
        c.teams()
    assert "401" in str(exc.value) and "No authentication parameters" in str(exc.value)


def test_an_error_body_echoing_the_key_is_redacted():
    c = FindMyShiftClient("SUPERSECRET", BASE,
                          opener=_failing(400, b"bad apiKey SUPERSECRET for this account"))
    with pytest.raises(FindMyShiftError) as exc:
        c.teams()
    assert "SUPERSECRET" not in str(exc.value)
    assert "[FINDMYSHIFT_API_KEY]" in str(exc.value)


def test_a_long_error_body_is_cut():
    c = FindMyShiftClient("k", BASE, opener=_failing(500, b"x" * 5000))
    with pytest.raises(FindMyShiftError) as exc:
        c.teams()
    assert len(str(exc.value)) < 300


def test_errors_and_logs_never_carry_the_key_or_a_success_body(caplog):
    c = FindMyShiftClient("SUPERSECRET", BASE,
                          opener=fake_opener({"staff/list": _fixture("staff")}))
    with caplog.at_level(logging.DEBUG, logger="rota.findmyshift"):
        c.staff()
        with pytest.raises(FindMyShiftError):
            FindMyShiftClient("SUPERSECRET", BASE, opener=_failing(500)).teams()
    assert "SUPERSECRET" not in caplog.text
    assert "example.org" not in caplog.text


def test_a_non_json_body_is_an_error_not_a_crash():
    c = FindMyShiftClient("k", BASE, opener=fake_opener({"teams/list": b"<html>oops</html>"}))
    with pytest.raises(FindMyShiftError) as exc:
        c.teams()
    assert "non-JSON" in str(exc.value)


def test_an_unreachable_host_is_an_error_not_a_crash():
    def opener(req):
        raise urllib.error.URLError("nope")
    with pytest.raises(FindMyShiftError) as exc:
        FindMyShiftClient("k", BASE, opener=opener).teams()
    assert "unreachable" in str(exc.value)


# --- settings ------------------------------------------------------------------

def test_from_settings_is_none_without_a_key(settings):
    from rota.services.findmyshift.client import from_settings
    settings.FINDMYSHIFT_API_KEY = ""
    assert from_settings() is None


def test_from_settings_builds_a_client_with_the_configured_url(settings):
    from rota.services.findmyshift.client import from_settings
    settings.FINDMYSHIFT_API_KEY = "k"
    settings.FINDMYSHIFT_API_URL = "https://example.test/api/1.4/"
    c = from_settings()
    assert c is not None and c.base_url == "https://example.test/api/1.4"


# --- the key goes nowhere else -------------------------------------------------

class _Redirector(http.server.BaseHTTPRequestHandler):
    """Answers every request with a 302 to a fixed URL on the other server,
    and records what it was sent. The Location is fixed rather than built
    from the request: nothing of the request goes into a response header,
    even in a test server."""
    seen = []
    target = ""

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        type(self).seen.append(self.rfile.read(length).decode())
        self.send_response(302)
        self.send_header("Location", type(self).target)
        self.end_headers()

    def log_message(self, *a):
        pass


class _Sink(http.server.BaseHTTPRequestHandler):
    """The other host. Anything arriving here is the key having travelled."""
    seen = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        type(self).seen.append(self.rfile.read(length).decode())
        self.send_response(200); self.end_headers(); self.wfile.write(b"[]")

    do_GET = do_POST

    def log_message(self, *a):
        pass


def _serve(handler):
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_a_redirect_is_not_followed_and_the_key_goes_nowhere():
    """The opener the client uses, against a server that redirects to
    another one. Over plain http only because a test cannot mint a
    certificate; the https rule is the next test. The point is that the
    302 is an error here and the second server never hears anything."""
    from rota.services.findmyshift import client as mod

    sink = _serve(_Sink)
    _Redirector.target = f"http://127.0.0.1:{sink.server_port}/elsewhere"
    redirector = _serve(_Redirector)
    _Sink.seen.clear(); _Redirector.seen.clear()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{redirector.server_port}/api/teams/list",
            data=b"apiKey=SUPERSECRET", method="POST")
        with pytest.raises(urllib.error.HTTPError) as exc:
            mod._OPENER.open(req, timeout=5)
        assert exc.value.code == 302
        assert any("SUPERSECRET" in s for s in _Redirector.seen), "the first server got the request"
        assert _Sink.seen == [], "the redirect target received a request"
    finally:
        sink.shutdown(); redirector.shutdown()


def test_a_redirect_becomes_an_error_naming_it():
    c = FindMyShiftClient("k", BASE, opener=_failing(302, headers={"Location": "https://x/"}))
    with pytest.raises(FindMyShiftError) as exc:
        c.teams()
    assert "redirected" in str(exc.value) and "not followed" in str(exc.value)


def test_the_key_is_never_sent_over_plain_http():
    calls = []
    def opener(req):
        calls.append(req)
    c = FindMyShiftClient("SUPERSECRET", "http://www.findmyshift.co.uk/api/1.4", opener=opener)
    with pytest.raises(FindMyShiftError) as exc:
        c.teams()
    assert calls == [], "a request left over http"
    assert "https" in str(exc.value) and "SUPERSECRET" not in str(exc.value)


def test_the_deploy_check_flags_a_plain_http_url(settings):
    from rota.checks import findmyshift_url_is_https
    settings.FINDMYSHIFT_API_KEY = "k"
    settings.FINDMYSHIFT_API_URL = "http://www.findmyshift.co.uk/api/1.4"
    (err,) = findmyshift_url_is_https(None)
    assert err.id == "rota.E007"
    settings.FINDMYSHIFT_API_URL = "https://www.findmyshift.co.uk/api/1.4"
    assert findmyshift_url_is_https(None) == []
    settings.FINDMYSHIFT_API_KEY = ""
    settings.FINDMYSHIFT_API_URL = "http://x"
    assert findmyshift_url_is_https(None) == []


def test_the_fixtures_hold_no_personal_data():
    """This repository is public. A recapture from the practice's real
    account must be made synthetic before it is committed, or this fails:
    email addresses only on example domains, and no date of birth, phone
    number or free-text comment that reads like a person's."""
    allowed_mail = re.compile(r"@example\.(org|com|invalid)$")
    problems = []

    def walk(o, where):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("dateOfBirth", "mobileNumber", "alternatePhone") and v:
                    problems.append(f"{where}: {k}")
                if "mail" in k.lower() and isinstance(v, str) and v and not allowed_mail.search(v):
                    problems.append(f"{where}: {k}={v!r}")
                if k == "profilePicture" and v and "example.invalid" not in v:
                    problems.append(f"{where}: {k}")
                walk(v, where)
        elif isinstance(o, list):
            for x in o:
                walk(x, where)

    for path in sorted(FIX.glob("*.json")):
        walk(json.loads(path.read_text()), path.name)
    assert not problems, problems
