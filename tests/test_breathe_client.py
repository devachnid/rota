"""The Breathe client, against recorded responses. No network.

tests/fixtures/breathe/ holds the test account's real responses, recorded
once. A fake opener serves them, so these tests prove how the client reads
Breathe without ever calling it.
"""

import io
import json
import logging
import re
from pathlib import Path
from urllib.error import HTTPError

import pytest

from rota.services.breathe.client import (EMPLOYEE_FIELDS, MAX_PAGES,
                                          BreatheClient, BreatheError)

FIX = Path(__file__).resolve().parent / "fixtures" / "breathe"
BASE = "https://api.breathehr.com/v1"
# The pathless form BREATHE_API_URL invites, and what rstrip("/") makes of
# "https://api.breathehr.com/". A prefix test cannot defend it.
BARE = "https://api.breathehr.com"


class _Resp(io.BytesIO):
    """Enough of an HTTPResponse for the client: body, headers, status."""
    def __init__(self, body: bytes, headers: dict, status=200):
        super().__init__(body)
        self.headers = headers
        self.status = status
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


def _headers_from(name):
    out = {}
    for line in (FIX / name).read_text().splitlines():
        if ":" in line and not line.startswith("HTTP/"):
            k, _, v = line.partition(":")
            out[k.strip().lower()] = v.strip()
    return out


def fake_opener(routes, seen=None):
    """routes: {url: (body_bytes, headers)}; records every request."""
    def opener(req):
        if seen is not None:
            seen.append(req)
        if req.full_url not in routes:
            raise HTTPError(req.full_url, 404, "not routed", {}, io.BytesIO(b""))
        body, headers = routes[req.full_url]
        if isinstance(body, HTTPError):
            raise body
        return _Resp(body, headers)
    return opener


def test_the_key_is_sent_as_the_x_api_key_header():
    seen = []
    routes = {f"{BASE}/sicknesses?per_page=100": ((FIX / "sicknesses.json").read_bytes(), {})}
    BreatheClient("k-test", BASE, opener=fake_opener(routes, seen)).fetch_all("sicknesses")
    assert seen[0].get_header("X-api-key") == "k-test"
    assert seen[0].get_header("Accept") == "application/json"


def test_fetch_all_follows_the_link_header_to_the_last_page():
    p1 = (FIX / "employees_page1.json").read_bytes()
    p2 = (FIX / "employees_page2.json").read_bytes()
    routes = {
        f"{BASE}/employees?per_page=100": (p1, _headers_from("employees_page1.headers")),
        f"{BASE}/employees?page=2&per_page=3": (p2, _headers_from("employees_page2.headers")),
        # page 2's Link names page 3; give it an empty page with no next
        f"{BASE}/employees?page=3&per_page=3": (b'{"employees": []}', {}),
    }
    rows = BreatheClient("k", BASE, opener=fake_opener(routes)).fetch_all("employees")
    assert len(rows) == 6, "three from page 1, three from page 2, none from page 3"
    assert rows[0]["id"] == json.loads(p1)["employees"][0]["id"]


def test_fetch_all_refuses_a_link_header_naming_a_foreign_host():
    """A Link header is attacker-reachable — from Breathe, or from anything on
    the network path. Following one to another host would attach the real
    X-API-KEY header to a request to that host."""
    seen = []
    p1 = (FIX / "employees_page1.json").read_bytes()
    evil_headers = {"link": '<https://evil.example.com/steal?page=2>; rel="next"'}
    routes = {f"{BASE}/employees?per_page=100": (p1, evil_headers)}
    with pytest.raises(BreatheError) as exc:
        BreatheClient("SUPERSECRETKEY", BASE, opener=fake_opener(routes, seen)).fetch_all("employees")
    assert len(seen) == 1, "the foreign host must never be requested"
    assert "SUPERSECRETKEY" not in str(exc.value)


@pytest.mark.parametrize("evil", [
    # A host that merely *starts with* the base: a registrable domain the
    # attacker owns, with the real one as a label prefix.
    "https://api.breathehr.com.evil.example/employees?page=2",
    # userinfo: everything before the "@" is a username, and the request
    # goes to evil.example.
    "https://api.breathehr.com@evil.example/employees?page=2",
], ids=["suffix-host", "userinfo-host"])
def test_fetch_all_refuses_a_link_that_only_string_prefixes_a_pathless_base(evil):
    """Against a pathless base, `startswith` passes both of these and the key
    goes to the attacker's host. The guard compares scheme and netloc."""
    seen = []
    p1 = (FIX / "employees_page1.json").read_bytes()
    routes = {f"{BARE}/employees?per_page=100": (p1, {"link": f'<{evil}>; rel="next"'})}
    with pytest.raises(BreatheError) as exc:
        BreatheClient("SUPERSECRETKEY", BARE,
                      opener=fake_opener(routes, seen)).fetch_all("employees")
    assert len(seen) == 1, "the foreign host must never be requested"
    assert "SUPERSECRETKEY" not in str(exc.value)


def test_fetch_all_follows_a_link_to_a_different_path_on_the_same_host():
    """The guard is scheme+host, not a path prefix: Breathe's own next links
    are still followed when the base carries a path."""
    p1 = (FIX / "employees_page1.json").read_bytes()
    routes = {
        f"{BASE}/employees?per_page=100":
            (p1, {"link": f'<{BASE}/employees?page=2&per_page=3>; rel="next"'}),
        f"{BASE}/employees?page=2&per_page=3": (b'{"employees": []}', {}),
    }
    rows = BreatheClient("k", BASE, opener=fake_opener(routes)).fetch_all("employees")
    assert len(rows) == 3


def test_fetch_all_stops_at_the_page_cap():
    """A Link header naming its own page is a loop that would spend the rate
    limit and never return."""
    seen = []
    body = b'{"employees": [{"id": 1}]}'
    headers = {"link": f'<{BASE}/employees?per_page=100>; rel="next"'}

    def opener(req):
        seen.append(req)
        return _Resp(body, headers)

    with pytest.raises(BreatheError) as exc:
        BreatheClient("SUPERSECRETKEY", BASE, opener=opener).fetch_all("employees")
    assert len(seen) == MAX_PAGES, "the cap bounds the requests, not just the loop"
    assert "SUPERSECRETKEY" not in str(exc.value)


def test_fetch_all_returns_the_list_under_the_resource_key():
    routes = {f"{BASE}/absences?per_page=100": ((FIX / "absences.json").read_bytes(), {})}
    rows = BreatheClient("k", BASE, opener=fake_opener(routes)).fetch_all("absences")
    assert isinstance(rows, list) and len(rows) == 2
    assert {r["id"] for r in rows} == {37454316, 37454317}


def test_employees_are_projected_to_the_allowed_fields_only():
    """The raw record carries NI number, bank details, salary and DOB. None of
    that may survive parsing."""
    routes = {f"{BASE}/employees?per_page=100": ((FIX / "employees.json").read_bytes(), {})}
    employees = BreatheClient("k", BASE, opener=fake_opener(routes)).employees()
    assert len(employees) == 11
    for e in employees:
        assert set(e) == set(EMPLOYEE_FIELDS), f"unexpected keys: {set(e) - set(EMPLOYEE_FIELDS)}"
    raw = json.loads((FIX / "employees.json").read_text())["employees"][0]
    for sensitive in ("national_insurance_no", "account_number", "sort_code", "salary", "dob", "address1"):
        assert sensitive in raw, "fixture no longer carries the field this test guards against"
        assert all(sensitive not in e for e in employees)


def test_a_429_raises_a_clear_error_and_does_not_retry():
    seen = []
    err = HTTPError(f"{BASE}/absences?per_page=100", 429, "Too Many Requests",
                    {"x-request-id": "abc-123"}, io.BytesIO(b'{"error":{"type":"Rate Limit Reached"}}'))
    routes = {f"{BASE}/absences?per_page=100": (err, {})}
    with pytest.raises(BreatheError) as exc:
        BreatheClient("k", BASE, opener=fake_opener(routes, seen)).fetch_all("absences")
    assert exc.value.status == 429
    assert exc.value.path == "/absences"
    assert exc.value.request_id == "abc-123"
    assert len(seen) == 1, "a rate-limited run aborts; the next is 15 minutes away"


def test_errors_never_carry_the_key_or_the_body(caplog):
    body = b'{"error":{"type":"Rate Limit Reached"},"secret_marker":"BODYTEXT"}'
    err = HTTPError(f"{BASE}/absences?per_page=100", 429, "x", {"x-request-id": "r1"}, io.BytesIO(body))
    routes = {f"{BASE}/absences?per_page=100": (err, {})}
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(BreatheError) as exc:
            BreatheClient("SUPERSECRETKEY", BASE, opener=fake_opener(routes)).fetch_all("absences")
    everything = str(exc.value) + caplog.text
    assert "SUPERSECRETKEY" not in everything
    assert "BODYTEXT" not in everything


def test_a_successful_fetch_logs_no_body(caplog):
    """test_errors_never_carry_the_key_or_the_body only drives the error path.
    The spec says a response body is never logged, not just an error one —
    absences.json's first record carries "Maternity" as a marker."""
    routes = {f"{BASE}/absences?per_page=100": ((FIX / "absences.json").read_bytes(), {})}
    with caplog.at_level(logging.DEBUG):
        BreatheClient("k", BASE, opener=fake_opener(routes)).fetch_all("absences")
    assert "Maternity" not in caplog.text


def test_a_non_json_body_is_a_breathe_error_not_a_crash():
    routes = {f"{BASE}/absences?per_page=100": (b"<html>maintenance</html>", {})}
    with pytest.raises(BreatheError):
        BreatheClient("k", BASE, opener=fake_opener(routes)).fetch_all("absences")


def test_from_settings_is_none_without_a_key(settings):
    from rota.services.breathe.client import from_settings
    settings.BREATHE_API_KEY = ""
    assert from_settings() is None


def test_from_settings_builds_a_client_with_the_configured_url(settings):
    from rota.services.breathe.client import from_settings
    settings.BREATHE_API_KEY = "k"
    settings.BREATHE_API_URL = "https://example.test/v1"
    c = from_settings()
    assert c is not None and c.base_url == "https://example.test/v1"


def test_the_repository_never_contains_the_test_accounts_key():
    """The key was shared in conversation for exploration. It lives in the
    environment on the server and nowhere else."""
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in root.rglob("*"):
        if path.is_dir() or ".git" in path.parts or ".venv" in path.parts:
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        if re.search(r"prod-[A-Za-z0-9_\-]{20,}", text):
            offenders.append(str(path.relative_to(root)))
    assert not offenders, f"a Breathe API key is committed in: {offenders}"
