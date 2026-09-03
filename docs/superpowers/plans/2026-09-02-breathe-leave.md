# Leave from BreatheHR — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Leave stops being requested or approved in this app; it is read from BreatheHR, shown on every screen, and respected by the fill engine.

**Architecture:** A read-only client over `urllib`, a sync that fetches all three Breathe leave endpoints and writes a deduplicated overlay table, and an availability resolver that reads the overlay part-by-part. Leave is never a rota entry. Everything local that managed leave is deleted.

**Tech Stack:** Django 5.2 LTS, SQLite WAL, Python 3.13, `urllib.request`, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-02-breathe-leave-design.md`

## Global Constraints

- **No build step, no node, no new dependencies.** The HTTP client is `urllib.request`.
- **Secrets from the environment only.** `BREATHE_API_KEY` and `BREATHE_API_URL` are read from the environment in `config/settings.py`. **The key appears in no file in the repository, no test, no fixture, and no log line.** A test asserts the last two.
- **The test suite makes no network calls.** Every client and sync test runs against `tests/fixtures/breathe/*.json`, which are already recorded from the test account and committed.
- Every colour from `tokens.css`; **no hex, `rgb(`, `rgba(`, `hsl(`, `hsla(` in `components.css` or `screens.css`**.
- All schedule mutations in `rota/services/*`. The sync is one.
- Run tests as `SECRET_KEY=throwaway .venv/bin/python -m pytest`; `manage.py` likewise. `DEBUG` defaults off and `SECRET_KEY` has no default.
- **Every task ends on a green suite.** The suite is **793 passing** at the start. Tests whose subject this plan removes are removed with it; tests whose fixture was a `LeaveRequest` get a `BreatheAbsence` fixture and keep their assertions word for word; **no assertion is weakened**. Each such edit is named in the task that makes it.
- **One deliberate deviation from the spec:** the spec says "one migration". This plan uses two — `0022` adds, `0023` removes — because the removal breaks every importer of `LeaveRequest` at once, and a task that adds and removes in one step cannot land green until five other tasks are also done. Two migrations cost nothing (there is no data) and let every task be reviewed on a passing suite.
- Sensitive Breathe fields — NI number, bank details, salary, date of birth, sickness type — are **discarded at the client boundary**, and tests assert they are absent from every projection and every stored row.

---

### Task 1: Half-day expansion

The pure function that turns a Breathe date range with half-day flags into the AM/PM parts off on a given day. It has no Django dependency and is the one piece of logic every screen and the fill engine will share, so it gets its own truth table.

**Files:**
- Create: `rota/services/breathe/__init__.py` (empty)
- Create: `rota/services/breathe/halfdays.py`
- Test: `tests/test_breathe_halfdays.py`

**Interfaces:**
- Produces: `rota.services.breathe.halfdays.Span` — a frozen dataclass with fields `start_date: date`, `end_date: date`, `half_start: bool`, `half_start_am_pm: str | None`, `half_end: bool`, `half_end_am_pm: str | None`, and a classmethod `Span.from_api(row: dict) -> Span` that reads those six keys from a Breathe record (dates as ISO strings).
- Produces: `parts_off(span: Span, day: date) -> frozenset[str]` — a subset of `{"AM", "PM"}`; empty when `day` is outside the span or when a single-day span's flags contradict each other.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_breathe_halfdays.py`:

```python
"""The half-day truth table from the spec, row by row.

Breathe records a range with four half-day fields. This module is the one
place that turns them into the rota's AM/PM parts, and it is pure, so it is
tested exhaustively here rather than through a screen.
"""

from datetime import date

import pytest

from rota.services.breathe.halfdays import Span, parts_off

MON, TUE, WED = date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16)


def span(start, end, hs=False, hs_ampm=None, he=False, he_ampm=None):
    return Span(start_date=start, end_date=end, half_start=hs,
                half_start_am_pm=hs_ampm, half_end=he, half_end_am_pm=he_ampm)


def test_a_day_strictly_inside_the_range_is_fully_off():
    assert parts_off(span(MON, WED), TUE) == {"AM", "PM"}


def test_a_day_outside_the_range_is_not_off():
    assert parts_off(span(MON, TUE), WED) == frozenset()
    assert parts_off(span(TUE, WED), MON) == frozenset()


def test_a_full_first_day_is_fully_off():
    assert parts_off(span(MON, WED), MON) == {"AM", "PM"}


def test_a_half_start_in_the_afternoon_leaves_the_morning_working():
    assert parts_off(span(MON, WED, hs=True, hs_ampm="PM"), MON) == {"PM"}


def test_a_half_start_in_the_morning_is_a_morning_off():
    assert parts_off(span(MON, WED, hs=True, hs_ampm="AM"), MON) == {"AM"}


def test_a_half_end_in_the_morning_leaves_the_afternoon_working():
    assert parts_off(span(MON, WED, he=True, he_ampm="AM"), WED) == {"AM"}


def test_a_half_end_in_the_afternoon_is_an_afternoon_off():
    assert parts_off(span(MON, WED, he=True, he_ampm="PM"), WED) == {"PM"}


def test_half_flags_only_apply_to_their_own_end():
    """A half start must not shorten the last day, nor a half end the first."""
    s = span(MON, WED, hs=True, hs_ampm="PM", he=True, he_ampm="AM")
    assert parts_off(s, MON) == {"PM"}
    assert parts_off(s, TUE) == {"AM", "PM"}
    assert parts_off(s, WED) == {"AM"}


def test_a_single_day_with_consistent_flags_is_that_one_part():
    assert parts_off(span(MON, MON, hs=True, hs_ampm="AM", he=True, he_ampm="AM"), MON) == {"AM"}
    assert parts_off(span(MON, MON, hs=True, hs_ampm="PM"), MON) == {"PM"}


def test_a_single_day_with_contradictory_flags_is_nothing():
    """AM-start and PM-end on one day cannot both be true. The spec says: no
    parts, and the sync logs it — never guess."""
    assert parts_off(span(MON, MON, hs=True, hs_ampm="AM", he=True, he_ampm="PM"), MON) == frozenset()


def test_a_half_flag_with_no_am_pm_value_is_treated_as_a_full_day():
    """Breathe sends half_start=false with am_pm=null routinely. If it ever
    sends half_start=true with a null am_pm, the record is malformed; erring
    towards 'off all day' keeps someone off the rota rather than on it."""
    assert parts_off(span(MON, WED, hs=True, hs_ampm=None), MON) == {"AM", "PM"}


def test_span_from_api_reads_the_six_breathe_fields():
    row = {"start_date": "2026-09-14", "end_date": "2026-09-16",
           "half_start": True, "half_start_am_pm": "PM",
           "half_end": False, "half_end_am_pm": None, "id": 1, "other": "x"}
    s = Span.from_api(row)
    assert s == span(MON, WED, hs=True, hs_ampm="PM")
```

- [ ] **Step 2: Run and watch them fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_breathe_halfdays.py -q
```

Expected: `ModuleNotFoundError: No module named 'rota.services.breathe'`.

- [ ] **Step 3: Write the module**

Create `rota/services/breathe/__init__.py` empty, and `rota/services/breathe/halfdays.py`:

```python
"""Breathe's half-day fields, turned into the rota's AM/PM parts.

A Breathe record is a date range with four extra fields: whether the first
day is a half day and which half, and the same for the last. This is the one
place that reads them. Everything that asks "is this clinician off on this
day, this part?" — the resolver, and through it every screen and the fill
engine — comes here, so the table below is the whole contract.
"""

from dataclasses import dataclass
from datetime import date

ALL = frozenset({"AM", "PM"})


@dataclass(frozen=True)
class Span:
    start_date: date
    end_date: date
    half_start: bool
    half_start_am_pm: str | None
    half_end: bool
    half_end_am_pm: str | None

    @classmethod
    def from_api(cls, row: dict) -> "Span":
        return cls(
            start_date=date.fromisoformat(row["start_date"]),
            end_date=date.fromisoformat(row["end_date"]),
            half_start=bool(row.get("half_start")),
            half_start_am_pm=row.get("half_start_am_pm"),
            half_end=bool(row.get("half_end")),
            half_end_am_pm=row.get("half_end_am_pm"),
        )


def _half(flag: bool, am_pm: str | None) -> frozenset[str]:
    """The parts a half-day flag keeps off. A set flag with no AM/PM value is
    malformed; treating it as a full day keeps the clinician off the rota
    rather than on it, which is the safer error."""
    if not flag or am_pm not in ("AM", "PM"):
        return ALL
    return frozenset({am_pm})


def parts_off(span: Span, day: date) -> frozenset[str]:
    """Which of AM/PM `day` is off for, under `span`.

    Empty outside the range. On the first day the half-start rule applies,
    on the last the half-end rule, and on a single-day span both — so
    contradictory flags (AM-start, PM-end) intersect to nothing, which is
    what the spec asks for: a Breathe data error is not something to guess at.
    """
    if not (span.start_date <= day <= span.end_date):
        return frozenset()
    parts = ALL
    if day == span.start_date:
        parts &= _half(span.half_start, span.half_start_am_pm)
    if day == span.end_date:
        parts &= _half(span.half_end, span.half_end_am_pm)
    return parts
```

- [ ] **Step 4: Run the tests**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_breathe_halfdays.py -q
```

Expected: 12 passed.

- [ ] **Step 5: Run the full suite and commit**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
git add rota/services/breathe/ tests/test_breathe_halfdays.py
git commit -m "feat: Breathe half-day fields become AM/PM parts

The one place that reads half_start/half_end and their am_pm values. Pure,
so the whole truth table is tested here rather than through a screen. A
single-day record whose flags contradict each other yields no parts —
guessing would put someone on or off the rota on a coin toss."
```

Expected: 805 passed.

---

### Task 2: The client

`urllib` over `X-API-KEY`, following the `Link` header, projecting employees to the few fields the app may hold, and never logging a body or the key.

**Files:**
- Create: `rota/services/breathe/client.py`
- Modify: `config/settings.py` (two settings, after `TRUSTED_PROXY_IPS`)
- Test: `tests/test_breathe_client.py`

**Interfaces:**
- Produces: `BreatheError(Exception)` with attributes `status: int | None`, `path: str`, `request_id: str | None`.
- Produces: `class BreatheClient: __init__(self, api_key: str, base_url: str = "https://api.breathehr.com/v1", *, opener=None, timeout: int = 20)`. `opener` is a callable `(urllib.request.Request) -> response`; tests inject one. `fetch_all(self, resource: str) -> list[dict]` follows pagination and returns the list under the resource key. `employees(self) -> list[dict]` returns `fetch_all("employees")` projected to `EMPLOYEE_FIELDS`.
- Produces: `EMPLOYEE_FIELDS = ("id", "first_name", "last_name", "email", "employee_ref", "status", "leaving_date")`.
- Produces: `from_settings() -> BreatheClient | None` — `None` when `settings.BREATHE_API_KEY` is empty.
- Settings: `BREATHE_API_KEY = os.environ.get("BREATHE_API_KEY", "")`, `BREATHE_API_URL = os.environ.get("BREATHE_API_URL", "https://api.breathehr.com/v1")`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_breathe_client.py`:

```python
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

from rota.services.breathe.client import (EMPLOYEE_FIELDS, BreatheClient,
                                          BreatheError)

FIX = Path(__file__).resolve().parent / "fixtures" / "breathe"
BASE = "https://api.breathehr.com/v1"


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
```

- [ ] **Step 2: Run and watch them fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_breathe_client.py -q
```

Expected: `ImportError` on `rota.services.breathe.client`.

- [ ] **Step 3: Add the settings**

In `config/settings.py`, immediately after the `TRUSTED_PROXY_IPS` block, add:

```python
# BreatheHR, which owns leave. Read-only. The key comes from /etc/rota.env
# like SECRET_KEY and never from a file in this repository; with no key the
# integration is off and every consumer degrades quietly.
BREATHE_API_KEY = os.environ.get("BREATHE_API_KEY", "")
BREATHE_API_URL = os.environ.get("BREATHE_API_URL", "https://api.breathehr.com/v1")
```

- [ ] **Step 4: Write the client**

Create `rota/services/breathe/client.py`:

```python
"""A read-only client for the BreatheHR API, on the standard library.

Facts this is built on, all measured against the test account rather than
read from documentation (the docs site renders client-side and is empty to
a fetcher):

  - Auth is an `X-API-KEY` header.
  - Pagination is a `Link` header carrying rel="next"; per_page caps at 100.
  - 60 requests per 60 seconds per customer; 429 on breach.
  - Employee records carry NI number, bank details, salary and date of birth.
    They are projected to EMPLOYEE_FIELDS the moment the response is parsed
    and nothing else is ever held — not in a cache, not in a log.

The client never logs a response body or the key. Errors carry the URL path,
the status and Breathe's x-request-id, which is what their support asks for.
"""

import json
import logging
import re
import urllib.error
import urllib.request
from urllib.parse import urlencode

from django.conf import settings

log = logging.getLogger("rota.breathe")

EMPLOYEE_FIELDS = ("id", "first_name", "last_name", "email", "employee_ref",
                   "status", "leaving_date")

PER_PAGE = 100
_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


class BreatheError(Exception):
    def __init__(self, message, *, status=None, path="", request_id=None):
        super().__init__(message)
        self.status = status
        self.path = path
        self.request_id = request_id


class BreatheClient:
    def __init__(self, api_key, base_url="https://api.breathehr.com/v1", *,
                 opener=None, timeout=20):
        self._key = api_key
        self.base_url = base_url.rstrip("/")
        self._open = opener or (lambda req: urllib.request.urlopen(req, timeout=timeout))

    # -- one page ----------------------------------------------------------

    def _get(self, url):
        path = url[len(self.base_url):].split("?")[0]
        req = urllib.request.Request(url, headers={
            "X-API-KEY": self._key,
            "Accept": "application/json",
        })
        try:
            with self._open(req) as resp:
                raw = resp.read()
                headers = {k.lower(): v for k, v in dict(resp.headers).items()}
        except urllib.error.HTTPError as e:
            rid = e.headers.get("x-request-id") if e.headers else None
            log.warning("breathe %s -> %s (x-request-id %s)", path, e.code, rid)
            raise BreatheError(f"Breathe returned {e.code} for {path}",
                               status=e.code, path=path, request_id=rid) from None
        except (urllib.error.URLError, OSError) as e:
            log.warning("breathe %s unreachable: %s", path, e.__class__.__name__)
            raise BreatheError(f"Breathe unreachable for {path}", path=path) from None
        try:
            return json.loads(raw), headers
        except ValueError:
            log.warning("breathe %s returned a non-JSON body", path)
            raise BreatheError(f"Breathe returned a non-JSON body for {path}",
                               path=path, request_id=headers.get("x-request-id")) from None

    # -- every page --------------------------------------------------------

    def fetch_all(self, resource):
        """Every row of `resource`, following Link: rel="next" to the end.

        No date filters: /absences filters by overlap and /leave_requests by
        start date, so a windowed fetch would silently miss leave that began
        before the window. Practice-scale data makes the full fetch cheap.
        """
        url = f"{self.base_url}/{resource}?{urlencode({'per_page': PER_PAGE})}"
        rows = []
        while url:
            data, headers = self._get(url)
            page = data.get(resource, [])
            rows.extend(page)
            m = _NEXT.search(headers.get("link", ""))
            url = m.group(1) if (m and page) else None
        return rows

    def employees(self):
        """Employees, projected. This is the only place the raw record exists
        in memory, and it does not leave this function."""
        return [{k: e.get(k) for k in EMPLOYEE_FIELDS}
                for e in self.fetch_all("employees")]


def from_settings():
    """A client from settings, or None when the integration is off."""
    if not settings.BREATHE_API_KEY:
        return None
    return BreatheClient(settings.BREATHE_API_KEY, settings.BREATHE_API_URL)
```

- [ ] **Step 5: Run the client tests**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_breathe_client.py -q
```

Expected: 10 passed. If `test_fetch_all_follows_the_link_header_to_the_last_page` fails on the page-2 URL, compare the exact `Link` URL in `tests/fixtures/breathe/employees_page1.headers` against the route key — the fixture is authoritative.

- [ ] **Step 6: Full suite and commit**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
git add rota/services/breathe/client.py config/settings.py tests/test_breathe_client.py
git commit -m "feat: a read-only BreatheHR client on the standard library

Follows the Link header, projects employees to seven fields at the parse
boundary so NI numbers and bank details never exist past it, and never logs
a body or the key. A 429 aborts the run rather than retrying — the next
sync is fifteen minutes away."
```

Expected: 815 passed.

---

### Task 3: The overlay models and the additive migration

`BreatheAbsence`, `BreatheLeaveMapping`, `BreatheSyncRun`, and `Clinician.breathe_employee_id`. Nothing is removed yet and nothing is registered in admin yet — admin registration lands with its documentation in Task 10, because `tests/test_docs.py` requires every registered model to be documented.

**Files:**
- Create: `rota/models/breathe.py`
- Modify: `rota/models/people.py` (one field, after `end_date`)
- Modify: `rota/models/__init__.py`
- Create: `rota/migrations/0022_breathe.py` (generate, then add the seed)
- Test: `tests/test_breathe_models.py`

**Interfaces:**
- Produces: `BreatheAbsence` with fields `clinician` (FK, `related_name="breathe_absences"`), `start_date`, `end_date`, `half_start`, `half_start_am_pm` (CharField 2, null), `half_end`, `half_end_am_pm`, `kind` (choices `holiday`/`other`/`sickness`), `reason` (CharField 100, blank), `source_ids` (CharField 100). Property `span -> Span`. `class Kind(models.TextChoices)`. Unique constraint `breathe_absence_content_key` on the seven content fields.
- Produces: `BreatheLeaveMapping(kind, reason, session_type)` with `Meta.unique_together = [("kind", "reason")]`, and `@classmethod as_dict() -> dict[tuple[str, str], SessionType]`.
- Produces: `BreatheSyncRun(started, finished, ok, n_requests, n_absences, n_sicknesses, n_deduped, n_unlinked, error)`.
- Produces: `Clinician.breathe_employee_id` — `PositiveIntegerField(null=True, blank=True, unique=True)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_breathe_models.py`:

```python
"""The overlay tables the sync writes and everything else reads."""

from datetime import date

import pytest
from django.db import IntegrityError

from rota.models import BreatheAbsence, BreatheLeaveMapping, Clinician, SessionType
from tests.factories import make_clinician, make_session_type

pytestmark = pytest.mark.django_db

MON = date(2026, 9, 14)


def _absence(c, **kw):
    kw.setdefault("start_date", MON); kw.setdefault("end_date", MON)
    kw.setdefault("kind", BreatheAbsence.Kind.HOLIDAY)
    kw.setdefault("source_ids", "1")
    return BreatheAbsence.objects.create(clinician=c, **kw)


def test_the_content_key_is_unique_per_clinician():
    """Two endpoints returning the same leave collide here, not in a loop."""
    c = make_clinician()
    _absence(c)
    with pytest.raises(IntegrityError):
        _absence(c, source_ids="2")


def test_different_half_day_flags_are_different_rows():
    c = make_clinician()
    _absence(c)
    _absence(c, half_start=True, half_start_am_pm="PM", source_ids="2")
    assert BreatheAbsence.objects.count() == 2


def test_span_exposes_the_half_day_fields():
    c = make_clinician()
    a = _absence(c, end_date=date(2026, 9, 16), half_end=True, half_end_am_pm="AM")
    assert a.span.half_end_am_pm == "AM" and a.span.end_date == date(2026, 9, 16)


def test_mapping_resolves_exact_reason_then_kind_default():
    al = make_session_type("Annual leave", code="AL", category="ABSENCE")
    mat = make_session_type("Maternity", code="MAT", category="ABSENCE")
    oth = make_session_type("Other leave", code="OTH", category="ABSENCE")
    BreatheLeaveMapping.objects.all().delete()
    BreatheLeaveMapping.objects.create(kind="holiday", reason="", session_type=al)
    BreatheLeaveMapping.objects.create(kind="other", reason="", session_type=oth)
    BreatheLeaveMapping.objects.create(kind="other", reason="Maternity", session_type=mat)
    m = BreatheLeaveMapping.as_dict()
    assert m[("holiday", "")] == al
    assert m[("other", "Maternity")] == mat
    assert m[("other", "")] == oth
    assert ("other", "Paternity") not in m, "no exact row; callers fall back to the kind default"


def test_the_migration_seeded_three_types_and_three_defaults():
    """The seed is the whole configuration a fresh install needs."""
    kinds = {m.kind for m in BreatheLeaveMapping.objects.filter(reason="")}
    assert kinds == {"holiday", "other", "sickness"}
    for code in ("AL", "SICK", "OTH"):
        t = SessionType.objects.get(code=code)
        assert t.category == SessionType.Category.ABSENCE


def test_mapping_session_type_must_be_an_absence_type():
    rout = make_session_type("Routine", code="ROUT")
    m = BreatheLeaveMapping(kind="holiday", reason="x", session_type=rout)
    with pytest.raises(Exception):
        m.full_clean()


def test_breathe_employee_id_is_unique_but_optional():
    a = make_clinician("A", breathe_employee_id=100)
    make_clinician("B")  # unlinked is fine
    make_clinician("C")  # two unlinked are fine (NULLs do not collide)
    with pytest.raises(IntegrityError):
        make_clinician("D", breathe_employee_id=100)
```

- [ ] **Step 2: Run and watch them fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_breathe_models.py -q
```

Expected: `ImportError: cannot import name 'BreatheAbsence'`.

- [ ] **Step 3: Write the models**

Create `rota/models/breathe.py`:

```python
"""Leave as read from BreatheHR. Written only by the sync; never by a view.

These rows are an overlay, not rota entries. Putting leave in the entry
table as well as here would be two answers to one question — the failure
the availability consolidation exists to prevent.
"""

from django.db import models

from rota.services.breathe.halfdays import Span


class BreatheAbsence(models.Model):
    class Kind(models.TextChoices):
        HOLIDAY = "holiday", "Holiday"
        OTHER = "other", "Other leave"
        SICKNESS = "sickness", "Sickness"

    clinician = models.ForeignKey(
        "rota.Clinician", on_delete=models.CASCADE, related_name="breathe_absences")
    start_date = models.DateField()
    end_date = models.DateField()
    half_start = models.BooleanField(default=False)
    half_start_am_pm = models.CharField(max_length=2, null=True, blank=True)
    half_end = models.BooleanField(default=False)
    half_end_am_pm = models.CharField(max_length=2, null=True, blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    # Breathe's leave_reason name for `other`; blank for holiday; ALWAYS blank
    # for sickness — the sickness type is health data and is discarded by the
    # sync before this row is built, not hidden at render.
    reason = models.CharField(max_length=100, blank=True, default="")
    # Diagnostic: which Breathe ids this row was built from. Comma-separated,
    # because one deduplicated row can come from two endpoints.
    source_ids = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        verbose_name = "Breathe absence"
        constraints = [
            models.UniqueConstraint(
                fields=["clinician", "start_date", "end_date", "half_start",
                        "half_start_am_pm", "half_end", "half_end_am_pm"],
                name="breathe_absence_content_key",
            ),
        ]
        ordering = ["start_date", "clinician_id"]

    @property
    def span(self) -> Span:
        return Span(self.start_date, self.end_date, self.half_start,
                    self.half_start_am_pm, self.half_end, self.half_end_am_pm)

    def __str__(self):
        return f"{self.clinician} {self.kind} {self.start_date}..{self.end_date}"


class BreatheLeaveMapping(models.Model):
    """How a Breathe record becomes a chip: (kind, reason) -> an absence type.
    A blank reason is the kind's default. Resolution: exact, then default."""
    kind = models.CharField(max_length=10, choices=BreatheAbsence.Kind.choices)
    reason = models.CharField(max_length=100, blank=True, default="")
    session_type = models.ForeignKey(
        "rota.SessionType", on_delete=models.PROTECT, related_name="+",
        limit_choices_to={"category": "ABSENCE"})

    class Meta:
        verbose_name = "Breathe leave mapping"
        unique_together = [("kind", "reason")]
        ordering = ["kind", "reason"]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.session_type_id and self.session_type.category != "ABSENCE":
            raise ValidationError({"session_type": "Must be an absence-category type."})

    @classmethod
    def as_dict(cls):
        return {(m.kind, m.reason): m.session_type
                for m in cls.objects.select_related("session_type")}

    def __str__(self):
        return f"{self.kind}/{self.reason or '*'} -> {self.session_type.code}"


class BreatheSyncRun(models.Model):
    started = models.DateTimeField()
    finished = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    n_requests = models.PositiveIntegerField(default=0)
    n_absences = models.PositiveIntegerField(default=0)
    n_sicknesses = models.PositiveIntegerField(default=0)
    n_deduped = models.PositiveIntegerField(default=0)
    n_unlinked = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Breathe sync run"
        ordering = ["-started"]

    def __str__(self):
        state = "ok" if self.ok else "failed"
        return f"{self.started:%Y-%m-%d %H:%M} {state}"
```

In `rota/models/people.py`, after the `end_date` field on `Clinician`, add:

```python
    # The Breathe employee this clinician is. Linked by hand in admin (a
    # dropdown of employees); unique so two clinicians can never share one
    # person's leave; nullable because a locum or a new starter may have no
    # Breathe record yet. Unlinked clinicians have no leave and are treated
    # as available — surfaced as an admin warning, not hidden.
    breathe_employee_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
```

In `rota/models/__init__.py`, add `from .breathe import BreatheAbsence, BreatheLeaveMapping, BreatheSyncRun` and the three names to `__all__`.

- [ ] **Step 4: Generate the migration, then add the seed**

```bash
SECRET_KEY=throwaway .venv/bin/python manage.py makemigrations rota -n breathe
```

Expected: `rota/migrations/0022_breathe.py` with three `CreateModel`s and one `AddField`. Open it and append a data migration to `operations`:

```python
def seed(apps, schema_editor):
    SessionType = apps.get_model("rota", "SessionType")
    Mapping = apps.get_model("rota", "BreatheLeaveMapping")
    defaults = {
        "holiday":  ("AL",   "Annual leave", "neutral-strong"),
        "sickness": ("SICK", "Sick",         "amber-strong"),
        "other":    ("OTH",  "Other leave",  "neutral-soft"),
    }
    for kind, (code, name, colour) in defaults.items():
        st = SessionType.objects.filter(code=code, category="ABSENCE").first()
        if st is None:
            st, _ = SessionType.objects.get_or_create(
                name=name, defaults={"code": code, "category": "ABSENCE", "colour": colour})
        Mapping.objects.get_or_create(kind=kind, reason="", defaults={"session_type": st})


def unseed(apps, schema_editor):
    apps.get_model("rota", "BreatheLeaveMapping").objects.filter(reason="").delete()
```

and `migrations.RunPython(seed, unseed)` as the last operation. The three tint keys are generated, not literal, so grep will not find them; confirm they exist with `.venv/bin/python -c "from rota import palette; print(all(k in palette.TINTS for k in ('neutral-strong','amber-strong','neutral-soft')))"` — it must print `True`.

- [ ] **Step 5: Run the model tests, then check migrations are consistent**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_breathe_models.py -q
SECRET_KEY=throwaway .venv/bin/python manage.py makemigrations --check --dry-run
```

Expected: 7 passed; "No changes detected".

- [ ] **Step 6: Full suite and commit**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
git add rota/models/breathe.py rota/models/people.py rota/models/__init__.py rota/migrations/0022_breathe.py tests/test_breathe_models.py
git commit -m "feat: the tables Breathe leave is read into

An overlay, never rota entries. The content key is a unique constraint so
the two-endpoint overlap collides in the database rather than in a loop.
Sickness reason is a field that is always blank by design. Seeds three
absence types and their default mappings — the whole configuration a fresh
install needs."
```

Expected: 822 passed.

---

### Task 4: The sync and its management command

Fetch all three endpoints, filter, normalise, deduplicate by content, resolve clinicians, replace the overlay in one transaction, log the run.

**Files:**
- Create: `rota/services/breathe/sync.py`
- Create: `rota/management/commands/breathe_sync.py`
- Test: `tests/test_breathe_sync.py`

**Interfaces:**
- Consumes: `BreatheClient.fetch_all(resource)`; `Span.from_api`; the models from Task 3.
- Produces: `rota.services.breathe.sync.run(client, *, dry_run=False, now=None) -> BreatheSyncRun` (unsaved when `dry_run`). Raises nothing to the caller: a failure is recorded on the run with `ok=False` and `error` set, and the previous overlay is untouched.
- Produces: `normalise(kind, row) -> Norm | None` where `Norm` is a frozen dataclass `(employee_id, span: Span, kind, reason, source_id)`; returns `None` for rows to drop (pending, declined, cancelled).
- Produces: management command `breathe_sync` with `--dry-run`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_breathe_sync.py`:

```python
"""The sync, against the recorded test account. No network.

The fixtures hold the case that shaped the design: two records that appear
in both /absences and /leave_requests, field-for-field, under different ids.
"""

import json
from datetime import date
from pathlib import Path

import pytest
from django.utils import timezone

from rota.models import BreatheAbsence, BreatheSyncRun
from rota.services.breathe import sync
from rota.services.breathe.client import BreatheError
from tests.factories import make_clinician

pytestmark = pytest.mark.django_db

FIX = Path(__file__).resolve().parent / "fixtures" / "breathe"


class FakeClient:
    """Serves the fixtures; `fail` names a resource that raises instead."""
    def __init__(self, fail=None, **overrides):
        self.fail = fail
        self.data = {r: json.loads((FIX / f"{r}.json").read_text())[r]
                     for r in ("leave_requests", "absences", "sicknesses")}
        self.data.update(overrides)
        self.calls = []
    def fetch_all(self, resource):
        self.calls.append(resource)
        if resource == self.fail:
            raise BreatheError("boom", status=500, path=f"/{resource}")
        return self.data[resource]


def _link_everyone():
    """Link a clinician to every employee id that has leave in the fixtures."""
    ids = {2340351, 2340352, 2340353, 2340356, 2340359, 2340361}
    return {i: make_clinician(f"Emp {i}", breathe_employee_id=i) for i in ids}


def test_the_two_endpoint_overlap_becomes_one_row_with_both_ids():
    by_id = _link_everyone()
    run = sync.run(FakeClient())
    assert run.ok
    tom = by_id[2340351]
    rows = BreatheAbsence.objects.filter(clinician=tom).order_by("start_date")
    assert [(r.start_date, r.end_date) for r in rows] == [
        (date(2026, 9, 14), date(2026, 9, 22)), (date(2026, 9, 28), date(2026, 9, 30))]
    mat = rows[0]
    assert mat.kind == "other" and mat.reason == "Maternity"
    assert set(mat.source_ids.split(",")) == {"44235958", "37454316"}, "request id first, absence id second"


def test_pending_requests_are_not_leave():
    by_id = _link_everyone()
    sync.run(FakeClient())
    li = by_id[2340356]  # the two pending rows in the fixture are his
    assert not BreatheAbsence.objects.filter(clinician=li).exists()


def test_cancelled_rows_are_dropped():
    by_id = _link_everyone()
    client = FakeClient()
    client.data["leave_requests"][2]["cancelled"] = True  # Kathleen's November holiday (2026-11-02)
    sync.run(client)
    kathleen = by_id[2340352]
    assert BreatheAbsence.objects.filter(clinician=kathleen).count() == 2


def test_sickness_type_never_reaches_the_row():
    by_id = _link_everyone()
    sync.run(FakeClient())
    sick = BreatheAbsence.objects.get(kind="sickness")
    assert sick.reason == ""
    raw = json.loads((FIX / "sicknesses.json").read_text())["sicknesses"][0]
    assert raw["company_sicknesstype"]["name"], "fixture no longer carries a type to guard against"


def test_unlinked_employees_are_counted_not_stored():
    make_clinician("Only Tom", breathe_employee_id=2340351)
    run = sync.run(FakeClient())
    assert run.ok
    assert BreatheAbsence.objects.count() == 3, "Tom's two leaves plus his sickness"
    assert run.n_unlinked == 9, "13 requests - 2 pending - Tom's 2 = 9 approved rows for unlinked people"


def test_counts_are_recorded():
    _link_everyone()
    run = sync.run(FakeClient())
    assert (run.n_requests, run.n_absences, run.n_sicknesses) == (13, 2, 1)
    assert run.n_deduped == 12, "11 approved requests + 1 sickness; both absences collided with requests"
    assert run.finished is not None


def test_a_failed_fetch_leaves_the_previous_overlay_untouched():
    _link_everyone()
    sync.run(FakeClient())
    before = list(BreatheAbsence.objects.values_list("id", "start_date", "clinician_id"))
    run = sync.run(FakeClient(fail="sicknesses"))
    assert run.ok is False and "sicknesses" in run.error
    assert list(BreatheAbsence.objects.values_list("id", "start_date", "clinician_id")) == before


def test_replace_all_removes_leave_that_disappeared_from_breathe():
    by_id = _link_everyone()
    sync.run(FakeClient())
    client = FakeClient()
    client.data["absences"] = []
    client.data["leave_requests"] = [r for r in client.data["leave_requests"]
                                    if r["employee"]["id"] != 2340351]
    sync.run(client)
    assert not BreatheAbsence.objects.filter(clinician=by_id[2340351], kind__in=["holiday", "other"]).exists()


def test_dry_run_writes_nothing_but_reports_counts():
    _link_everyone()
    run = sync.run(FakeClient(), dry_run=True)
    assert run.ok and run.n_deduped == 12
    assert BreatheAbsence.objects.count() == 0
    assert BreatheSyncRun.objects.count() == 0


def test_contradictory_single_day_flags_are_logged_and_kept(caplog):
    """The row is stored — parts_off yields nothing for it, so it has no
    effect — and the run notes it, so someone can fix it in Breathe."""
    by_id = _link_everyone()
    client = FakeClient()
    bad = dict(client.data["leave_requests"][0])
    bad.update({"id": 999, "start_date": "2026-12-01", "end_date": "2026-12-01",
                "half_start": True, "half_start_am_pm": "AM",
                "half_end": True, "half_end_am_pm": "PM"})
    client.data["leave_requests"].append(bad)
    import logging
    with caplog.at_level(logging.WARNING, logger="rota.breathe"):
        run = sync.run(client)
    assert run.ok
    assert "999" in caplog.text and "contradict" in caplog.text.lower()


def test_the_management_command_runs_and_reports(capsys):
    from django.core.management import call_command
    from unittest import mock
    _link_everyone()
    with mock.patch("rota.services.breathe.client.from_settings", return_value=FakeClient()):
        call_command("breathe_sync")
    out = capsys.readouterr().out
    assert "12" in out and "ok" in out.lower()
    assert BreatheSyncRun.objects.count() == 1


def test_the_command_exits_cleanly_when_the_integration_is_off(capsys, settings):
    from django.core.management import call_command
    settings.BREATHE_API_KEY = ""
    call_command("breathe_sync")
    assert "not configured" in capsys.readouterr().out.lower()
    assert BreatheSyncRun.objects.count() == 0
```

- [ ] **Step 2: Run and watch them fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_breathe_sync.py -q
```

Expected: `ImportError` on `rota.services.breathe.sync`.

- [ ] **Step 3: Write the sync**

Create `rota/services/breathe/sync.py`:

```python
"""Pull leave from Breathe into the overlay. One transaction, replace-all.

Three endpoints hold leave and, in the test account, do not agree: two
records appear in both /absences and /leave_requests under different ids,
while other approved requests appear in only one. So: fetch everything from
all three, filter, normalise to a content key, deduplicate on it, and
replace the overlay wholesale. A record cancelled in Breathe is simply
absent next time; nothing has to be reconciled.

Sources are walked in a fixed order and the first row seen for a key keeps
its kind and reason; later collisions contribute only their id.
"""

import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from rota.models import BreatheAbsence, BreatheSyncRun, Clinician
from rota.services.breathe.client import BreatheError
from rota.services.breathe.halfdays import Span, parts_off

log = logging.getLogger("rota.breathe")

SOURCES = ("leave_requests", "absences", "sicknesses")


@dataclass(frozen=True)
class Norm:
    employee_id: int
    span: Span
    kind: str
    reason: str
    source_id: str

    @property
    def key(self):
        s = self.span
        return (self.employee_id, s.start_date, s.end_date, s.half_start,
                s.half_start_am_pm, s.half_end, s.half_end_am_pm)


def _kind_and_reason(row):
    if row.get("type") == "Holiday":
        return BreatheAbsence.Kind.HOLIDAY, ""
    reason = (row.get("leave_reason") or row.get("reason") or {}).get("name") or ""
    return BreatheAbsence.Kind.OTHER, reason


def normalise(source, row):
    """A Norm, or None for a row that is not leave."""
    if row.get("cancelled"):
        return None
    if source == "leave_requests" and row.get("status") != "approved":
        return None
    if source == "sicknesses":
        kind, reason = BreatheAbsence.Kind.SICKNESS, ""  # the type is dropped here
    else:
        kind, reason = _kind_and_reason(row)
    return Norm(employee_id=row["employee"]["id"], span=Span.from_api(row),
                kind=kind, reason=reason, source_id=str(row["id"]))


def _warn_on_contradictions(norm):
    s = norm.span
    if s.start_date == s.end_date and not parts_off(s, s.start_date):
        log.warning("breathe record %s for employee %s on %s has contradictory "
                    "half-day flags and covers no parts", norm.source_id,
                    norm.employee_id, s.start_date)


def run(client, *, dry_run=False, now=None):
    started = now or timezone.now()
    result = BreatheSyncRun(started=started)

    try:
        fetched = {s: client.fetch_all(s) for s in SOURCES}
    except BreatheError as e:
        result.error = f"{e} (x-request-id {e.request_id})"
        result.finished = timezone.now()
        if not dry_run:
            result.save()
        return result

    result.n_requests = len(fetched["leave_requests"])
    result.n_absences = len(fetched["absences"])
    result.n_sicknesses = len(fetched["sicknesses"])

    merged = {}
    for source in SOURCES:
        for row in fetched[source]:
            norm = normalise(source, row)
            if norm is None:
                continue
            held = merged.get(norm.key)
            if held is None:
                merged[norm.key] = norm
                _warn_on_contradictions(norm)
            else:
                merged[norm.key] = Norm(held.employee_id, held.span, held.kind,
                                        held.reason, f"{held.source_id},{norm.source_id}")
    result.n_deduped = len(merged)

    by_employee = {c.breathe_employee_id: c for c in
                   Clinician.objects.exclude(breathe_employee_id=None)}
    rows, unlinked = [], 0
    for norm in merged.values():
        clinician = by_employee.get(norm.employee_id)
        if clinician is None:
            unlinked += 1
            continue
        s = norm.span
        rows.append(BreatheAbsence(
            clinician=clinician, start_date=s.start_date, end_date=s.end_date,
            half_start=s.half_start, half_start_am_pm=s.half_start_am_pm,
            half_end=s.half_end, half_end_am_pm=s.half_end_am_pm,
            kind=norm.kind, reason=norm.reason, source_ids=norm.source_id))
    result.n_unlinked = unlinked
    result.ok = True
    result.finished = timezone.now()

    if dry_run:
        return result
    with transaction.atomic():
        BreatheAbsence.objects.all().delete()
        BreatheAbsence.objects.bulk_create(rows)
        result.save()
    return result
```

- [ ] **Step 4: Write the command**

Create `rota/management/commands/breathe_sync.py`:

```python
"""Pull leave from BreatheHR into the rota's overlay.

Run by deploy/rota-breathe.timer every fifteen minutes, and by the
"Refresh now" button on the Breathe sync admin page. --dry-run fetches and
counts without writing, which is how to check a real account's shape.
"""

from django.core.management.base import BaseCommand

from rota.services.breathe import client as breathe_client
from rota.services.breathe import sync


class Command(BaseCommand):
    help = "Read leave from BreatheHR into the overlay the rota displays."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="fetch and count, write nothing")

    def handle(self, *args, dry_run=False, **options):
        client = breathe_client.from_settings()
        if client is None:
            self.stdout.write("Breathe is not configured (BREATHE_API_KEY unset); nothing to do.")
            return
        run = sync.run(client, dry_run=dry_run)
        if not run.ok:
            self.stderr.write(f"Breathe sync failed: {run.error}")
            return
        self.stdout.write(
            f"Breathe sync ok{' (dry run)' if dry_run else ''}: "
            f"{run.n_requests} requests, {run.n_absences} absences, "
            f"{run.n_sicknesses} sicknesses -> {run.n_deduped} after dedup, "
            f"{run.n_unlinked} for unlinked employees")
```

- [ ] **Step 5: Run the sync tests**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_breathe_sync.py -q
```

Expected: 12 passed. The counts in the tests are derived from the fixtures; if one fails, recount from `tests/fixtures/breathe/*.json` before touching the assertion — the fixture is the authority, and the test names why each number is what it is.

- [ ] **Step 6: Full suite and commit**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
git add rota/services/breathe/sync.py rota/management/commands/breathe_sync.py tests/test_breathe_sync.py
git commit -m "feat: the Breathe sync — fetch all, dedupe by content, replace the overlay

Three endpoints that do not agree, unioned and deduplicated on the content
key in a fixed source order. Replace-all in one transaction, so leave
cancelled in Breathe is simply absent next time. A failed fetch writes
nothing and the previous overlay stands."
```

Expected: 834 passed.

---

### Task 5: The resolver reads the overlay, part by part

The load-bearing change. `AvailabilityResolver` takes `BreatheAbsence` rows and a mapping instead of `LeaveRequest`s; `leave_type` gains a `part`; `cell_state`'s `ghost_leave` becomes `absence` and the dashed ghost styling goes. Every call site and every test that built a `LeaveRequest` fixture for these paths moves to the overlay. `LeaveRequest` still exists after this task — nothing in the resolver's path reads it any more.

**Files:**
- Modify: `rota/services/availability.py` (`AvailabilityResolver.__init__`, `leave_type`, `on_leave`)
- Modify: `rota/services/cells.py`
- Modify: `rota/services/fill/context.py:28-33`
- Modify: `rota/views/grid.py:56-63`
- Modify: `rota/views/day.py` (the `approved_leave` block, and the partition at lines 112-122)
- Modify: `templates/rota/grid.html:55-59`, `templates/rota/day.html:53-57`
- Modify: `static/css/components.css:361-366` (delete `.chip.is-ghost`)
- Modify (fixture swap, assertions unchanged): `tests/test_availability_resolver.py`, `tests/test_cells.py`, `tests/test_fill_availability.py`, `tests/test_grid_rendering.py`, `tests/test_day_view.py`
- Modify (helper): `tests/factories.py` — add `make_absence`

**Interfaces:**
- Consumes: `BreatheAbsence`, `BreatheLeaveMapping.as_dict()`, `parts_off`.
- Produces: `AvailabilityResolver(pattern_rows, clinicians, absences, mapping)` — `absences` iterable of `BreatheAbsence`; `mapping` the dict from `as_dict()`. `leave_type(clinician_id, day, part) -> SessionType | None`. `on_leave(clinician_id, day, part) -> bool` unchanged in signature.
- Produces: `cell_state(...)` dict key `absence` (was `ghost_leave`). All other keys unchanged.
- Produces: `tests.factories.make_absence(clinician, start, end=None, kind="holiday", reason="", **half_flags) -> BreatheAbsence`.

- [ ] **Step 1: Add the factory**

Append to `tests/factories.py`:

```python
def make_absence(clinician, start, end=None, kind="holiday", reason="", **half):
    """A Breathe absence row, as the sync would write it."""
    from rota.models import BreatheAbsence
    return BreatheAbsence.objects.create(
        clinician=clinician, start_date=start, end_date=end or start,
        kind=kind, reason=reason, source_ids="test",
        half_start=half.get("half_start", False),
        half_start_am_pm=half.get("half_start_am_pm"),
        half_end=half.get("half_end", False),
        half_end_am_pm=half.get("half_end_am_pm"),
    )
```

- [ ] **Step 2: Write the new resolver tests**

Append to `tests/test_availability_resolver.py` (leave the existing tests in place for now; they are converted in Step 6):

```python
# --------------------------------------------------------- Breathe overlay ---

def _mapping():
    from rota.models import BreatheLeaveMapping
    return BreatheLeaveMapping.as_dict()


def test_a_full_day_absence_covers_both_parts():
    c = make_clinician(); rows = make_pattern(c)
    make_absence(c, MON)
    r = availability.AvailabilityResolver(rows, [c], [BreatheAbsence.objects.get()], _mapping())
    assert r.on_leave(c.id, MON, "AM") and r.on_leave(c.id, MON, "PM")
    assert r.available(c.id, MON, "AM") is False


def test_a_half_start_afternoon_leaves_the_morning_available():
    c = make_clinician(); rows = make_pattern(c)
    make_absence(c, MON, MON + timedelta(days=2), half_start=True, half_start_am_pm="PM")
    r = availability.AvailabilityResolver(rows, [c], list(BreatheAbsence.objects.all()), _mapping())
    assert r.on_leave(c.id, MON, "AM") is False
    assert r.on_leave(c.id, MON, "PM") is True
    assert r.on_leave(c.id, MON + timedelta(days=1), "AM") is True


def test_leave_type_resolves_through_the_mapping():
    c = make_clinician(); rows = make_pattern(c)
    make_absence(c, MON, kind="sickness")
    r = availability.AvailabilityResolver(rows, [c], list(BreatheAbsence.objects.all()), _mapping())
    assert r.leave_type(c.id, MON, "AM").code == "SICK"


def test_an_unmapped_reason_falls_back_to_the_kind_default():
    c = make_clinician(); rows = make_pattern(c)
    make_absence(c, MON, kind="other", reason="Jury service")
    r = availability.AvailabilityResolver(rows, [c], list(BreatheAbsence.objects.all()), _mapping())
    assert r.leave_type(c.id, MON, "AM").code == "OTH"


def test_leave_does_not_change_works_on():
    c = make_clinician(); rows = make_pattern(c)
    make_absence(c, MON)
    r = availability.AvailabilityResolver(rows, [c], list(BreatheAbsence.objects.all()), _mapping())
    assert r.works_on(c.id, MON, "AM") is True
```

Add `from rota.models import BreatheAbsence` and `from tests.factories import make_absence` to the imports.

- [ ] **Step 3: Run and watch them fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_availability_resolver.py -q -k "absence or half_start or mapping or default or works_on"
```

Expected: `TypeError` — the resolver does not take a fourth argument.

- [ ] **Step 4: Change the resolver**

In `rota/services/availability.py`, replace the `__init__` body's leave section and the two leave methods. Remove the `LeaveRequest` import from this module.

```python
    def __init__(self, pattern_rows, clinicians, absences, mapping=None):
        pattern_rows = list(pattern_rows)
        self._patterns = PatternResolver(pattern_rows)
        self._clinicians = {c.id: c for c in clinicians}
        self._with_pattern = {row.clinician_id for row in pattern_rows}

        # {clinician_id: [(span, session_type), ...]} from the Breathe overlay.
        # The mapping (kind, reason) -> type is resolved here, once, so a
        # lookup never touches the database. Exact reason first, then the
        # kind's default row; an unmapped kind renders nothing rather than
        # crashing, and the sync status page is where that gets noticed.
        mapping = mapping or {}
        self._leave = {}
        for a in absences:
            session_type = (mapping.get((a.kind, a.reason))
                            or mapping.get((a.kind, "")))
            if session_type is None:
                continue
            self._leave.setdefault(a.clinician_id, []).append((a.span, session_type))
```

```python
    def leave_type(self, clinician_id, day, part):
        """The absence type covering `day`/`part`, or None. Part-aware:
        Breathe records half-days, and the rota's parts are the unit."""
        for span, session_type in self._leave.get(clinician_id, ()):
            if part in parts_off(span, day):
                return session_type
        return None

    def on_leave(self, clinician_id, day, part):
        return self.leave_type(clinician_id, day, part) is not None
```

Add `from rota.services.breathe.halfdays import parts_off` at the top. Update the class docstring's fourth item from "approved leave" to "Breathe absences".

- [ ] **Step 5: Change `cell_state` and its callers**

`rota/services/cells.py`: rename the key and pass the part.

```python
    leave_type = resolver.leave_type(clinician_id, day, part) if entry is None else None
```
and in the returned dict `"absence": leave_type if ghostable else None,` replacing `"ghost_leave"`. Rename the local `ghostable` to `showable` and reword the comment block: the two guards are unchanged in shape — an absence renders only on a part the clinician works, or for a clinician with no pattern rows at all — but the reason is no longer "approval should have written an entry"; it is that a part-timer's day off must not read "AL" on a day they were never in. Update the module docstring's precedence line from "a ghosted leave chip" to "the Breathe absence".

`rota/services/fill/context.py:28-33`:
```python
        absences = BreatheAbsence.objects.filter(
            clinician__in=self.clinicians,
            start_date__lte=end, end_date__gte=start,
        )
        self._availability = availability.AvailabilityResolver(
            pattern_rows, self.clinicians, absences, BreatheLeaveMapping.as_dict())
```
Replace the `LeaveRequest` import with `BreatheAbsence, BreatheLeaveMapping`.

`rota/views/grid.py:56-63` — same shape, keeping the `if days:` guard and `min()/max()`:
```python
    absences = BreatheAbsence.objects.none()
    if days:
        absences = BreatheAbsence.objects.filter(
            clinician__in=active,
            start_date__lte=max(days), end_date__gte=min(days))
    resolver = availability.AvailabilityResolver(
        pattern_rows, active, absences, BreatheLeaveMapping.as_dict())
```

`rota/views/day.py`, the `approved_leave` block: same, for `target` alone. And the partition: replace `cell["ghost_leave"]` with `cell["absence"]` in the `elif`, and change the on-leave test so it consults the overlay rather than entries:

```python
        worked_cells = [cell for cell in cells if not cell["off"]]
        is_on_leave = bool(worked_cells) and all(
            cell["absence"] is not None
            or (cell["entry"] and cell["entry"].session_type.category == absence)
            for cell in worked_cells
        )
```
Update the comment above it: "covered" now means a Breathe absence on that part, or (for history) an absence-category entry.

- [ ] **Step 6: Convert the existing fixtures**

In each of these files, every `LeaveRequest.objects.create(clinician=c, session_type=al, start_date=X, end_date=Y, status=APPROVED)` becomes `make_absence(c, X, Y)`; a `PENDING` one becomes **no absence at all** (pending is not leave, and the assertion — that the clinician is available — stands). Where a test built its own `_resolver(clinicians, rows, leave)` helper, the helper passes `BreatheLeaveMapping.as_dict()` as the fourth argument. **Assertions do not change**, with one mechanical exception: assertions on the string `"is-ghost"` in rendered HTML become assertions on the absence chip's presence — the rendered code (`"AL"`) inside a `<span class="chip"` with `title="From Breathe"`. The three test names that assert a *ghost is suppressed* (closed day; contractual window) keep asserting the chip is absent.

- `tests/test_availability_resolver.py` — 13 references; then delete the pre-existing tests this task's Step 2 made redundant only where they test the *identical* behaviour with the old fixture (whole-day on both parts; leave does not change works_on). Keep every other assertion.
- `tests/test_cells.py` — 7 references; assert on `cell["absence"]`.
- `tests/test_fill_availability.py` — 5 references.
- `tests/test_grid_rendering.py` — 17 references; the docstring's precedence table changes its second line to "absence from Breathe".
- `tests/test_day_view.py` — 3 references.

Remove `LeaveRequest` from each file's imports once nothing uses it.

- [ ] **Step 7: Templates and CSS**

`templates/rota/grid.html:55-59` and `templates/rota/day.html:53-57` — replace the ghost branch with a normal chip:

```html
    {% elif cell.absence %}
      <span class="chip" title="From Breathe"
            style="--chip-bg: var(--tint-{{ cell.absence.tint.key }}-bg); --chip-fg: var(--tint-{{ cell.absence.tint.key }}-fg);">
        {{ cell.absence.code }}
      </span>
```

`static/css/components.css:361-366` — delete the `.chip.is-ghost` rule and the comment above it. Confirm nothing else references `is-ghost`:

```bash
grep -rn "is-ghost\|ghost_leave" rota/ templates/ static/ tests/
```

Expected: no output.

- [ ] **Step 8: Run the affected modules, then the full suite**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_availability_resolver.py tests/test_cells.py tests/test_fill_availability.py tests/test_grid_rendering.py tests/test_day_view.py tests/test_css_cascade.py tests/test_chrome_contrast.py -q
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
```

Expected: all pass. The full count is 834 plus the five new resolver tests minus the two made redundant: **837**, but the binding rule is green, not the number — report the number you get.

- [ ] **Step 9: Commit**

```bash
git add -A rota/services rota/views templates static/css/components.css tests/
git commit -m "refactor: the availability resolver reads Breathe absences, part by part

leave_type() gains a part, because Breathe records half-days and the rota's
parts are the unit. cell_state's ghost becomes an absence: a ghost warned
that approval had not written an entry, and there is no entry to be missing
now. Every fixture that built a LeaveRequest for these paths now builds a
BreatheAbsence; every assertion is unchanged."
```

---

### Task 6: My Schedule reads the overlay and drops the balance

The agenda stops bypassing `cell_state`, so a GP's own Breathe leave shows on their own schedule. The leave balance strip and the leave rows under "Your requests" go; swaps stay.

**Files:**
- Modify: `rota/views/my_schedule.py` (`_blocks`, the today block, the context)
- Modify: `templates/rota/my_schedule.html` (agenda rows, delete `ms-leave`, delete the `my_requests` loop, delete the "Request leave" button at line 10)
- Modify (subject removed): `tests/test_my_schedule.py::test_shows_upcoming_sessions_and_balance` — drop the `"60" in html` half; the `"ROUT" in html` half stays
- Test: `tests/test_my_schedule_weeks.py` (this branch's own file from Phase 2 — extend)

**Interfaces:**
- Consumes: `cell_state`, `AvailabilityResolver`, `BreatheAbsence`, `BreatheLeaveMapping`.
- Produces: each `days` row in a week block gains `"am_cell"` and `"pm_cell"` — the `cell_state` dicts — alongside the existing `am`/`pm` entries. Context loses `leave` and `my_requests`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_my_schedule_weeks.py`:

```python
# ------------------------------------------------------ Breathe overlay ---

def test_a_gps_own_breathe_leave_shows_on_their_schedule(gp_client, gp_user):
    """The old agenda bypassed cell_state and so could never show leave. With
    Breathe as the source that would hide a GP's own leave from them."""
    from tests.factories import make_absence
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    tuesday = monday + timedelta(days=1)
    make_absence(c, tuesday)
    html = gp_client.get("/me/").content.decode()
    assert 'title="From Breathe"' in html
    assert "AL" in html


def test_a_week_of_breathe_leave_reads_on_leave_all_week(gp_client, gp_user):
    from tests.factories import make_absence
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    make_absence(c, monday, monday + timedelta(days=4))
    PracticeSettings.load()
    weeks = gp_client.get("/me/").context["weeks"]
    assert weeks[0]["count_label"] == "On leave all week"


def test_today_reads_working_when_only_half_the_day_is_leave(gp_client, gp_user):
    from tests.factories import make_absence
    c = make_clinician(user=gp_user)
    make_pattern(c)
    today = date.today()
    if today.weekday() > 4:
        pytest.skip("weekend")
    make_absence(c, today, half_start=True, half_start_am_pm="AM")
    ctx = gp_client.get("/me/").context
    assert ctx["today_state"] == "working"
    assert ctx["today_cells"][0]["absence"] is not None
    assert ctx["today_cells"][1]["absence"] is None


def test_the_leave_balance_and_leave_requests_are_gone(gp_client, gp_user):
    make_clinician(user=gp_user)
    html = gp_client.get("/me/").content.decode()
    assert "ms-balance" not in html
    assert "Request leave" not in html
    assert "Propose a swap" in html, "swaps stay"
```

- [ ] **Step 2: Run and watch them fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_my_schedule_weeks.py -q -k "breathe or half_the_day or gone"
```

Expected: FAIL.

- [ ] **Step 3: Rewrite the view's data path**

In `rota/views/my_schedule.py`:

- Build a resolver once per request, after `entries_by`:
  ```python
      pattern_rows = list(PatternSlot.objects.filter(clinician=clinician))
      absences = BreatheAbsence.objects.filter(
          clinician=clinician, start_date__lte=last, end_date__gte=monday)
      resolver = availability.AvailabilityResolver(
          pattern_rows, [clinician], absences, BreatheLeaveMapping.as_dict())
  ```
- Change `_blocks(today, open_weekdays, closed, entries_by)` to `_blocks(clinician, today, open_weekdays, closed, entries_by, resolver)`. For each day build `am_cell`/`pm_cell` with `cell_state(clinician.id, day, part, entry=..., resolver=resolver, closed=not is_open)` and include a day when it is open **or** either cell has an `entry` **or** either cell has an `absence`. Compute `is_leave` as: every cell with `off` False has an `absence`, or has an absence-category entry. Compute the "On leave all week" label the same way across the block's worked cells. Replace the long docstring paragraph explaining the bypass with two sentences saying the agenda now goes through `cell_state` because Breathe is the source of leave and a GP must see their own.
- Today: `today_cells` becomes the two `cell_state` dicts; `today_state` is `"working"` when either cell has an `entry` or an `absence`, then the closed/not_in rules as before.
- Delete the `leave` and `my_requests` context keys and the `leave_svc` import; import `availability`, `cell_state`, `BreatheAbsence`, `BreatheLeaveMapping`, `PatternSlot`.

- [ ] **Step 4: Rewrite the template rows**

In `templates/rota/my_schedule.html`, the agenda row's two chip blocks become one include-free pattern, repeated for `row.am_cell` and `row.pm_cell`:

```html
        {% if row.am_cell.entry %}
        <span class="chip{% if not row.am_cell.entry.is_published %} is-draft{% endif %}"
              style="--chip-bg: var(--tint-{{ row.am_cell.entry.session_type.tint.key }}-bg); --chip-fg: var(--tint-{{ row.am_cell.entry.session_type.tint.key }}-fg);">
          {{ row.am_cell.entry.session_type.code }}{% if row.am_cell.entry.site %}<span class="site-marker">{{ row.am_cell.entry.site.name|slice:":1" }}</span>{% endif %}
        </span>
        {% elif row.am_cell.absence %}
        <span class="chip" title="From Breathe"
              style="--chip-bg: var(--tint-{{ row.am_cell.absence.tint.key }}-bg); --chip-fg: var(--tint-{{ row.am_cell.absence.tint.key }}-fg);">{{ row.am_cell.absence.code }}</span>
        {% else %}
        <span class="ms-dash">&mdash;</span>
        {% endif %}
```

The Today box's cells loop over `today_cells` with the same three-way branch. Delete the `<section class="ms-leave">` block, the `{% for r in my_requests %}` loop (keep the `my_swaps` loop and change the section's condition to `{% if my_swaps %}`), and the `Request leave` anchor at line 10.

- [ ] **Step 5: The one pre-existing assertion whose subject is gone**

`tests/test_my_schedule.py::test_shows_upcoming_sessions_and_balance`: the balance no longer exists, so `and "60" in html` is removed and the test is renamed `test_shows_upcoming_sessions`. `"ROUT" in html` stays. The `leave_entitlement_sessions=60` argument stays until Task 8 removes the field.

- [ ] **Step 6: Run and commit**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_my_schedule_weeks.py tests/test_my_schedule.py tests/test_template_hygiene.py -q
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
git add rota/views/my_schedule.py templates/rota/my_schedule.html tests/test_my_schedule_weeks.py tests/test_my_schedule.py
git commit -m "feat: My Schedule shows a GP's own Breathe leave; the balance goes

The agenda stops bypassing cell_state. That bypass was deliberate when the
only thing it hid was an admin integrity warning; with Breathe the source of
leave it would hide a GP's own leave from their own schedule. The leave
balance strip goes — Breathe is where a GP checks their allowance."
```

Expected: green; report the count.

---

### Task 7: Swaps refuse a session the colleague is off for

`swaps.validate()` has never consulted leave. With approval gone, this is the only gate.

**Files:**
- Modify: `rota/services/swaps.py` (`validate`)
- Test: `tests/test_swaps.py` is pre-existing; create `tests/test_swaps_breathe.py`

**Interfaces:**
- Consumes: `AvailabilityResolver`, `BreatheAbsence`, `BreatheLeaveMapping`, `PatternSlot`.
- Produces: `validate(req)` returns, in addition to its existing problems, one string per clinician-slot where the receiving clinician is on Breathe leave: `f"{clinician.name} is on leave on {day} {part} (from Breathe) and cannot take that session."` appended **after** the existing two lists, so existing ordering assertions hold.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_swaps_breathe.py`:

```python
"""A swap must not hand a session to someone Breathe says is off."""

from datetime import date

import pytest

from rota.models import SwapRequest
from rota.services import swaps
from tests.factories import make_absence, make_clinician, make_entry, make_pattern, make_session_type

pytestmark = pytest.mark.django_db

MON, TUE = date(2026, 9, 14), date(2026, 9, 15)


def _swap():
    a, b = make_clinician("Ann Able"), make_clinician("Bob Baker")
    make_pattern(a); make_pattern(b)
    rout = make_session_type("Routine", code="ROUT")
    make_entry(a, day=MON, part="AM", session_type=rout)
    make_entry(b, day=TUE, part="PM", session_type=rout)
    req = SwapRequest.objects.create(proposer=a, proposer_day=MON, proposer_part="AM",
                                     colleague=b, colleague_day=TUE, colleague_part="PM")
    return a, b, req


def test_a_clean_swap_has_no_problems():
    _, _, req = _swap()
    assert swaps.validate(req) == []


def test_the_colleague_being_on_leave_for_the_session_they_would_receive_is_refused():
    a, b, req = _swap()
    make_absence(b, MON)  # Bob would receive Ann's Monday AM, and is off Monday
    problems = swaps.validate(req)
    assert any("Bob Baker is on leave on 2026-09-14 AM" in p for p in problems)


def test_the_proposer_being_on_leave_for_the_session_they_would_receive_is_refused():
    a, b, req = _swap()
    make_absence(a, TUE, half_start=True, half_start_am_pm="PM")
    problems = swaps.validate(req)
    assert any("Ann Able is on leave on 2026-09-15 PM" in p for p in problems)


def test_leave_on_the_other_half_of_the_day_does_not_block():
    a, b, req = _swap()
    make_absence(b, MON, half_start=True, half_start_am_pm="PM")  # off Monday PM; receives AM
    assert swaps.validate(req) == []


def test_leave_problems_come_after_the_existing_kinds():
    """Existing tests pin the order of 'no session' then 'paired'; leave
    problems append after both."""
    a, b, req = _swap()
    from rota.models import RotaEntry
    RotaEntry.objects.filter(clinician=b).delete()  # Bob now has no session
    make_absence(a, TUE)
    problems = swaps.validate(req)
    assert "has no session" in problems[0]
    assert "is on leave" in problems[-1]
```

- [ ] **Step 2: Run and watch them fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_swaps_breathe.py -q
```

Expected: 3 failed (the leave ones), 2 passed.

- [ ] **Step 3: Add the check**

In `rota/services/swaps.py`, after the existing loop in `validate`, before the return:

```python
    # A swap gives each clinician the other's session. Neither may be on
    # Breathe leave for the session they would receive — this is the only
    # gate now that leave is not approved here. Built once per validation:
    # two clinicians, two slots.
    from rota.models import BreatheAbsence, BreatheLeaveMapping, PatternSlot
    from rota.services import availability
    people = [req.proposer, req.colleague]
    slots = list(involved_slots(req))
    days = [d for d, _ in slots]
    resolver = availability.AvailabilityResolver(
        PatternSlot.objects.filter(clinician__in=people),
        people,
        BreatheAbsence.objects.filter(clinician__in=people,
                                      start_date__lte=max(days), end_date__gte=min(days)),
        BreatheLeaveMapping.as_dict(),
    )
    on_leave = []
    receives = {req.proposer: (req.colleague_day, req.colleague_part),
                req.colleague: (req.proposer_day, req.proposer_part)}
    for clinician, (day, part) in receives.items():
        if resolver.on_leave(clinician.id, day, part):
            on_leave.append(
                f"{clinician.name} is on leave on {day} {part} (from Breathe) "
                "and cannot take that session.")
    return no_session + paired + on_leave
```

and change the existing `return no_session + paired` to fall through to this. Read `involved_slots` first to confirm it yields `(day, part)` pairs; the existing loop above already uses it that way.

- [ ] **Step 4: Run and commit**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_swaps_breathe.py tests/test_swaps.py -q
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
git add rota/services/swaps.py tests/test_swaps_breathe.py
git commit -m "feat: swaps refuse a session the receiving clinician is off for

validate() never consulted leave. With approval gone this is the only gate
between an agreed swap and a session handed to someone Breathe says is off."
```

Expected: green; report the count.

---

### Task 8: Remove everything that managed leave locally

The `LeaveRequest` model and every path that touched it. This task is large because the removal ripples, but it is one deliverable: after it, `grep -rn LeaveRequest rota/` finds nothing.

**Files:**
- Modify: `rota/models/requests.py` (delete `LeaveRequest`), `rota/models/__init__.py`, `rota/models/people.py` (delete `leave_entitlement_sessions`), `rota/models/catalog.py` (delete `counts_toward_entitlement` at line 45; `leave_year_start_month`/`_day` at lines 101-102)
- Create: `rota/migrations/0023_remove_local_leave.py` (generated)
- Delete: `rota/services/leave.py`, `templates/rota/leave_form.html`, `templates/rota/report_leave.html`, `tests/test_leave.py`, `tests/test_leave_preview.py`
- Modify: `rota/views/requests.py` (delete `leave_new`, `leave_approve`, `leave_decline`; strip the leave half of `inbox`; drop the `LeaveRequest`, `SessionType`, `leave_svc`, `date`-if-unused imports)
- Modify: `rota/views/reports.py` (delete `report_leave` and the `leave_svc` import)
- Modify: `rota/urls.py` (delete lines 21, 23-26, 36)
- Modify: `templates/rota/inbox.html` (delete lines 8-53, the Leave section), `templates/rota/grid.html:10` (delete the Request leave anchor)
- Modify: `rota/admin.py` (delete `LeaveRequestAdmin` and its import; remove `"leave_entitlement_sessions"` from `ClinicianAdmin.list_display`; remove `"counts_toward_entitlement"` from `SessionTypeAdmin.list_display`)
- Modify (subject removed): `tests/test_security.py` lines 157-158 and 191 — remove `"/reports/leave/"` and `"/me/leave/new/"` from the URL lists; `tests/test_template_hygiene.py:60-62` — same two URLs; `tests/test_reports.py` — delete the test(s) that request `/reports/leave/`; `tests/test_my_schedule.py:13` and `tests/test_clinician_lifecycle.py:79` — drop the `leave_entitlement_sessions` argument
- Test: `tests/test_breathe_removal.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: the absence of `LeaveRequest`. Task 9 and 10 assume it is gone.

- [ ] **Step 1: Write the removal test**

Create `tests/test_breathe_removal.py`:

```python
"""Local leave management is gone. Breathe owns it."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.django_db


def test_no_code_references_leaverequest():
    hits = []
    for path in (ROOT / "rota").rglob("*.py"):
        if "migrations" in path.parts:
            continue
        if re.search(r"\bLeaveRequest\b", path.read_text()):
            hits.append(str(path.relative_to(ROOT)))
    assert not hits, f"LeaveRequest still referenced in: {hits}"


def test_no_template_offers_a_leave_request():
    for path in (ROOT / "templates").rglob("*.html"):
        text = path.read_text()
        assert "leave/new" not in text, f"{path.name} still links the leave form"
        assert "Request leave" not in text, f"{path.name} still offers Request leave"


@pytest.mark.parametrize("url", ["/me/leave/new/", "/reports/leave/",
                                 "/requests/leave/1/approve/", "/requests/leave/1/decline/"])
def test_the_old_leave_urls_are_gone(admin_client, url):
    from rota.models import PracticeSettings
    PracticeSettings.load()
    assert admin_client.get(url).status_code == 404


def test_the_removed_fields_are_gone():
    from rota.models import Clinician, PracticeSettings, SessionType
    assert not any(f.name == "leave_entitlement_sessions" for f in Clinician._meta.fields)
    assert not any(f.name == "counts_toward_entitlement" for f in SessionType._meta.fields)
    assert not any(f.name.startswith("leave_year_start") for f in PracticeSettings._meta.fields)


def test_the_inbox_still_shows_swaps_and_no_leave(admin_client):
    from rota.models import PracticeSettings
    PracticeSettings.load()
    html = admin_client.get("/requests/").content.decode()
    assert "Swaps" in html or "swap" in html.lower()
    assert "pending leave" not in html.lower()
```

- [ ] **Step 2: Run and watch it fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_breathe_removal.py -q
```

Expected: FAIL on every test.

- [ ] **Step 3: Delete the model, fields, service and templates**

Delete the `LeaveRequest` class from `rota/models/requests.py` and its export from `rota/models/__init__.py`. Delete `leave_entitlement_sessions` from `Clinician`, `counts_toward_entitlement` from `SessionType`, `leave_year_start_month` and `leave_year_start_day` from `PracticeSettings`. Then:

```bash
git rm rota/services/leave.py templates/rota/leave_form.html templates/rota/report_leave.html tests/test_leave.py tests/test_leave_preview.py
SECRET_KEY=throwaway .venv/bin/python manage.py makemigrations rota -n remove_local_leave
```

Expected: `0023_remove_local_leave.py` with one `DeleteModel` and four `RemoveField`s. Nothing else.

- [ ] **Step 4: Views, URLs, templates, admin**

`rota/views/requests.py`: delete `leave_new`, `leave_approve`, `leave_decline`; in `inbox`, delete the `pending_leave` loop and the context key; drop the now-unused imports (`LeaveRequest`, `SessionType`, `leave_svc`; keep `date`, `Clinician`, `RotaEntry` if `swap_new` still uses them — it does).

`rota/views/reports.py`: delete `report_leave` and `from rota.services import leave as leave_svc`.

`rota/urls.py`: delete the `leave-new`, `leave-approve`, `leave-decline` and `report-leave` paths.

`templates/rota/inbox.html`: delete from `<h2>Leave</h2>` through the `No pending leave requests.` paragraph. `templates/rota/grid.html`: delete the `Request leave` anchor.

`rota/admin.py`: delete `LeaveRequestAdmin` and remove `LeaveRequest` from the import; remove `"leave_entitlement_sessions"` from `ClinicianAdmin.list_display` and `"counts_toward_entitlement"` from `SessionTypeAdmin.list_display`.

- [ ] **Step 5: The pre-existing tests whose subject is gone**

- `tests/test_security.py`: remove `"/reports/leave/"` and `"/me/leave/new/"` from the two URL lists at lines 157-158 and 191. Assertions unchanged.
- `tests/test_template_hygiene.py:60-62`: remove the same two URLs from the parametrize list.
- `tests/test_reports.py`: delete the test(s) that GET `/reports/leave/` and any `counts_toward_entitlement=True` / `leave_entitlement_sessions=` arguments they used.
- `tests/test_my_schedule.py:13`: drop `leave_entitlement_sessions=60`.
- `tests/test_clinician_lifecycle.py:79`: drop `"leave_entitlement_sessions": "0"` from the posted form data.

- [ ] **Step 6: Run everything**

```bash
grep -rn "LeaveRequest\|leave_svc\|counts_toward_entitlement\|leave_entitlement\|leave_year_start" rota/ templates/ tests/ --include=*.py --include=*.html | grep -v migrations
SECRET_KEY=throwaway .venv/bin/python manage.py makemigrations --check --dry-run
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
```

Expected: the grep prints nothing; "No changes detected"; green.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat!: remove local leave management — Breathe owns it

The request form, approval inbox, entitlement report, per-clinician
entitlement, the counts-toward-entitlement flag and the leave-year settings
all go. Swaps stay. Two test modules whose only subject was approval are
removed; four others lose a URL or an argument for a thing that no longer
exists and keep every remaining assertion."
```

---

### Task 9: The linking admin

The clinician form's Breathe field becomes a dropdown of employees, with an email match offered as a suggestion, degrading to a plain input when Breathe is unreachable.

**Files:**
- Modify: `rota/admin_widgets.py` (add `BreatheEmployeeSelect` and the cached employee loader)
- Modify: `rota/admin.py` (`ClinicianAdmin`: `formfield_for_dbfield`, `list_display`, `list_filter`, a `breathe_link` column, the suggestion on the add/change form)
- Test: `tests/test_breathe_admin.py` (new)

**Interfaces:**
- Consumes: `rota.services.breathe.client.from_settings()`, `BreatheClient.employees()`.
- Produces: `rota.admin_widgets.breathe_employees() -> list[dict] | None` — the projected employee list, cached 300 seconds in Django's default cache under key `breathe:employees`; `None` when unconfigured or unreachable. `BreatheEmployeeSelect(forms.Select)` whose `choices` are built from it.
- Produces: `ClinicianAdmin.breathe_link(obj)` list column; `list_filter` gains `BreatheLinkedFilter` (Linked / Not linked).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_breathe_admin.py`:

```python
"""Linking a clinician to a Breathe employee, in the admin."""

import json
from pathlib import Path
from unittest import mock

import pytest
from django.core.cache import cache

from rota.models import Clinician
from tests.factories import make_clinician

pytestmark = pytest.mark.django_db

FIX = Path(__file__).resolve().parent / "fixtures" / "breathe"
EMPLOYEES = [{k: e.get(k) for k in ("id", "first_name", "last_name", "email",
                                     "employee_ref", "status", "leaving_date")}
             for e in json.loads((FIX / "employees.json").read_text())["employees"]]


class FakeClient:
    def __init__(self, fail=False): self.fail = fail; self.calls = 0
    def employees(self):
        self.calls += 1
        if self.fail:
            from rota.services.breathe.client import BreatheError
            raise BreatheError("down", path="/employees")
        return EMPLOYEES


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear(); yield; cache.clear()


def _with(client):
    return mock.patch("rota.admin_widgets.from_settings", return_value=client)


def test_the_field_is_a_dropdown_of_employees(staff_client):
    with _with(FakeClient()):
        html = staff_client.get("/admin/rota/clinician/add/").content.decode()
    assert '<select name="breathe_employee_id"' in html
    assert "Anya Sharma" in html and "EMP001" in html
    assert "anya.sharma@" in html


def test_ex_employees_are_listed_and_marked(staff_client):
    with _with(FakeClient()):
        html = staff_client.get("/admin/rota/clinician/add/").content.decode()
    assert "James Jefferies" in html
    assert "ex-employee" in html.lower()


def test_the_employee_list_is_cached(staff_client):
    client = FakeClient()
    with _with(client):
        staff_client.get("/admin/rota/clinician/add/")
        staff_client.get("/admin/rota/clinician/add/")
    assert client.calls == 1


def test_unreachable_breathe_degrades_to_a_number_input(staff_client):
    with _with(FakeClient(fail=True)):
        html = staff_client.get("/admin/rota/clinician/add/").content.decode()
    assert '<input type="number" name="breathe_employee_id"' in html
    assert "could not reach breathe" in html.lower()


def test_unconfigured_breathe_degrades_the_same_way(staff_client):
    with mock.patch("rota.admin_widgets.from_settings", return_value=None):
        html = staff_client.get("/admin/rota/clinician/add/").content.decode()
    assert '<input type="number" name="breathe_employee_id"' in html


def test_an_email_match_is_preselected_on_an_unlinked_clinician(staff_client, gp_user):
    gp_user.email = "anya.sharma@breathehrdevachnidltd.com"; gp_user.save()
    c = make_clinician("Anya", user=gp_user)
    with _with(FakeClient()):
        html = staff_client.get(f"/admin/rota/clinician/{c.pk}/change/").content.decode()
    assert 'value="2340355" selected' in html


def test_a_suggestion_never_overrides_an_existing_link(staff_client, gp_user):
    gp_user.email = "anya.sharma@breathehrdevachnidltd.com"; gp_user.save()
    c = make_clinician("Anya", user=gp_user, breathe_employee_id=2340353)  # Omar, deliberately
    with _with(FakeClient()):
        html = staff_client.get(f"/admin/rota/clinician/{c.pk}/change/").content.decode()
    assert 'value="2340353" selected' in html
    assert 'value="2340355" selected' not in html


def test_saving_the_form_stores_the_link(staff_client):
    c = make_clinician("Link Me")
    with _with(FakeClient()):
        resp = staff_client.post(f"/admin/rota/clinician/{c.pk}/change/", {
            "name": "Link Me", "initials": "LM", "group": c.group_id, "active": "on",
            "breathe_employee_id": "2340357",
            "traineeprofile-TOTAL_FORMS": "0", "traineeprofile-INITIAL_FORMS": "0",
        })
    assert resp.status_code == 302, resp.content.decode()[:500]
    assert Clinician.objects.get(pk=c.pk).breathe_employee_id == 2340357


def test_the_list_shows_linked_name_and_filters(staff_client):
    make_clinician("Linked", breathe_employee_id=2340355)
    make_clinician("Loose")
    with _with(FakeClient()):
        html = staff_client.get("/admin/rota/clinician/").content.decode()
        linked = staff_client.get("/admin/rota/clinician/?breathe=linked").content.decode()
        loose = staff_client.get("/admin/rota/clinician/?breathe=unlinked").content.decode()
    assert "Anya Sharma" in html and "not linked" in html.lower()
    assert "Linked" in linked and "Loose" not in linked
    assert "Loose" in loose and "Linked" not in loose
```

If the inline formset management-form keys in `test_saving_the_form_stores_the_link` differ, read the rendered change form's hidden inputs and use its exact names; the assertion is on the stored link, not the form plumbing.

- [ ] **Step 2: Run and watch them fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_breathe_admin.py -q
```

Expected: FAIL.

- [ ] **Step 3: The widget and the loader**

Append to `rota/admin_widgets.py`:

```python
from django import forms
from django.core.cache import cache

from rota.services.breathe.client import BreatheError, from_settings

_EMPLOYEES_KEY = "breathe:employees"
_EMPLOYEES_TTL = 300


def breathe_employees():
    """The projected employee list, or None when Breathe is off or down.
    Cached so opening ten clinician forms costs one request."""
    cached = cache.get(_EMPLOYEES_KEY)
    if cached is not None:
        return cached
    client = from_settings()
    if client is None:
        return None
    try:
        employees = client.employees()
    except BreatheError:
        return None
    cache.set(_EMPLOYEES_KEY, employees, _EMPLOYEES_TTL)
    return employees


def employee_label(e):
    name = f"{e.get('first_name') or ''} {e.get('last_name') or ''}".strip()
    bits = [name, e.get("email") or "", e.get("employee_ref") or ""]
    label = " · ".join(b for b in bits if b)
    if (e.get("status") or "").lower().startswith("ex"):
        label += " (ex-employee)"
    return label


class BreatheEmployeeSelect(forms.Select):
    """A dropdown of Breathe employees; built per form so the cache decides
    how often Breathe is actually asked."""

    def __init__(self, employees, attrs=None):
        choices = [("", "— not linked —")] + [
            (e["id"], employee_label(e))
            for e in sorted(employees, key=lambda e: (e.get("last_name") or "", e.get("first_name") or ""))
        ]
        super().__init__(attrs, choices)
```

- [ ] **Step 4: Wire the admin**

In `rota/admin.py`, on `ClinicianAdmin`:

```python
    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "breathe_employee_id":
            employees = breathe_employees()
            if employees is None:
                field = super().formfield_for_dbfield(db_field, request, **kwargs)
                field.help_text = ("Could not reach Breathe, so this is the raw employee id. "
                                   "The dropdown returns when Breathe is reachable.")
                return field
            kwargs["widget"] = BreatheEmployeeSelect(employees)
            kwargs["help_text"] = "The Breathe employee whose leave this clinician's is."
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Suggest by exact email match — only for a clinician with no link, and
        # only as an initial value the admin must still submit.
        if obj is not None and obj.breathe_employee_id is None and obj.user_id:
            employees = breathe_employees() or []
            email = (obj.user.email or "").lower()
            match = next((e for e in employees if (e.get("email") or "").lower() == email), None)
            if match and "breathe_employee_id" in form.base_fields:
                form.base_fields["breathe_employee_id"].initial = match["id"]
        return form

    @admin.display(description="Breathe")
    def breathe_link(self, obj):
        if obj.breathe_employee_id is None:
            return format_html('<span style="color: var(--muted, #6b7280)">not linked</span>')
        employees = breathe_employees() or []
        e = next((x for x in employees if x["id"] == obj.breathe_employee_id), None)
        return employee_label(e) if e else f"#{obj.breathe_employee_id}"
```

Note `form.base_fields[...].initial` sets the initial for **this form class instance**, which Django builds per request in `get_form`; it does not leak across requests. Add `"breathe_link"` to `list_display` and a filter:

```python
class BreatheLinkedFilter(admin.SimpleListFilter):
    title = "Breathe"
    parameter_name = "breathe"
    def lookups(self, request, model_admin):
        return [("linked", "Linked"), ("unlinked", "Not linked")]
    def queryset(self, request, qs):
        if self.value() == "linked":
            return qs.exclude(breathe_employee_id=None)
        if self.value() == "unlinked":
            return qs.filter(breathe_employee_id=None)
        return qs
```

and `list_filter = ("group", "active", BreatheLinkedFilter)`. Import `breathe_employees`, `employee_label`, `BreatheEmployeeSelect` from `rota.admin_widgets`. The hex fallback in `breathe_link` is inside the Django admin, which is not governed by the tokens rule (it is a stock admin page, not `components.css`/`screens.css`); `tests/test_chrome_contrast.py` scans only those two sheets.

- [ ] **Step 5: Run and commit**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_breathe_admin.py tests/test_clinician_lifecycle.py tests/test_docs.py -q
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
git add rota/admin_widgets.py rota/admin.py tests/test_breathe_admin.py
git commit -m "feat: link a clinician to a Breathe employee from a dropdown

Populated from Breathe and cached five minutes; degrades to a plain input
with a note when Breathe is down, so a third party being unreachable never
blocks editing a clinician. An exact email match is pre-selected on an
unlinked clinician and never overrides an existing link."
```

Expected: green.

---

### Task 10: The sync status page, Refresh now, the unlinked warning — and their documentation

Registers the three Breathe models in admin, which `tests/test_docs.py` requires to be documented — so `docs/admin/breathe.md` ships in this task.

**Files:**
- Modify: `rota/admin.py` (three registrations; `BreatheSyncRunAdmin` with a custom changelist and a `refresh` view)
- Create: `templates/admin/rota/breathesyncrun/change_list.html`
- Modify: `rota/views/grid.py` (the unlinked count into the warnings, admins only)
- Modify: `templates/rota/grid.html` (render it where warnings render)
- Create: `docs/admin/breathe.md`; modify `docs/admin/README.md` (index row and a troubleshooting row)
- Test: `tests/test_breathe_status.py` (new)

**Interfaces:**
- Consumes: `sync.run`, `from_settings`, `BreatheSyncRun`, `Clinician`.
- Produces: admin URL name `admin:rota_breathesyncrun_refresh` (POST). Grid context key `unlinked_count` (int, admins only; 0 otherwise).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_breathe_status.py`:

```python
"""The Breathe sync status page, Refresh now, and the unlinked warning."""

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from rota.models import BreatheSyncRun, PracticeSettings
from tests.factories import make_clinician

pytestmark = pytest.mark.django_db


def _run(ok=True, minutes_ago=30, **kw):
    started = timezone.now() - timedelta(minutes=minutes_ago)
    return BreatheSyncRun.objects.create(started=started, finished=started, ok=ok, **kw)


def test_the_status_page_shows_the_last_good_run_and_unlinked_clinicians(staff_client):
    _run(n_deduped=12, n_unlinked=3)
    make_clinician("Nobody Linked")
    html = staff_client.get("/admin/rota/breathesyncrun/").content.decode()
    assert "12" in html and "Last successful sync" in html
    assert "Nobody Linked" in html


def test_the_status_page_shows_the_last_error(staff_client):
    _run(ok=True, minutes_ago=60)
    _run(ok=False, minutes_ago=5, error="Breathe returned 429 for /absences")
    html = staff_client.get("/admin/rota/breathesyncrun/").content.decode()
    assert "429" in html


def test_refresh_now_runs_a_sync(staff_client):
    with mock.patch("rota.admin.breathe_client.from_settings", return_value=object()), \
         mock.patch("rota.admin.breathe_sync.run") as run:
        run.return_value = BreatheSyncRun(started=timezone.now(), ok=True, n_deduped=4)
        resp = staff_client.post("/admin/rota/breathesyncrun/refresh/")
    assert resp.status_code == 302
    run.assert_called_once()


def test_refresh_now_refuses_within_sixty_seconds_of_a_run(staff_client):
    BreatheSyncRun.objects.create(started=timezone.now() - timedelta(seconds=20), ok=True)
    with mock.patch("rota.admin.breathe_sync.run") as run:
        staff_client.post("/admin/rota/breathesyncrun/refresh/", follow=True)
    run.assert_not_called()


def test_refresh_now_is_post_only_and_admin_only(client, gp_client):
    assert gp_client.post("/admin/rota/breathesyncrun/refresh/").status_code in (302, 403)
    assert client.post("/admin/rota/breathesyncrun/refresh/").status_code in (302, 403)


def test_refresh_now_says_so_when_unconfigured(staff_client):
    with mock.patch("rota.admin.breathe_client.from_settings", return_value=None):
        resp = staff_client.post("/admin/rota/breathesyncrun/refresh/", follow=True)
    assert "not configured" in resp.content.decode().lower()


def test_admins_see_an_unlinked_warning_on_the_grid(admin_client):
    PracticeSettings.load()
    make_clinician("A"); make_clinician("B", breathe_employee_id=1)
    html = admin_client.get("/rota/").content.decode()
    assert "1 clinician not linked to Breathe" in html


def test_gps_do_not_see_the_unlinked_warning(gp_client, gp_user):
    PracticeSettings.load()
    make_clinician("Me", user=gp_user); make_clinician("Other")
    assert "not linked to Breathe" not in gp_client.get("/rota/").content.decode()


def test_no_warning_when_everyone_is_linked(admin_client):
    PracticeSettings.load()
    make_clinician("A", breathe_employee_id=1)
    assert "not linked to Breathe" not in admin_client.get("/rota/").content.decode()
```

- [ ] **Step 2: Run and watch them fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_breathe_status.py -q
```

Expected: FAIL.

- [ ] **Step 3: Register the models and add the refresh view**

In `rota/admin.py`, import `from rota.services.breathe import client as breathe_client, sync as breathe_sync`, the three models, and add:

```python
@admin.register(BreatheAbsence)
class BreatheAbsenceAdmin(admin.ModelAdmin):
    list_display = ("clinician", "kind", "reason", "start_date", "end_date",
                    "half_start_am_pm", "half_end_am_pm")
    list_filter = ("kind",)
    readonly_fields = [f.name for f in BreatheAbsence._meta.fields]
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False


@admin.register(BreatheLeaveMapping)
class BreatheLeaveMappingAdmin(admin.ModelAdmin):
    list_display = ("kind", "reason", "session_type")
    list_filter = ("kind",)


@admin.register(BreatheSyncRun)
class BreatheSyncRunAdmin(admin.ModelAdmin):
    list_display = ("started", "ok", "n_deduped", "n_unlinked", "error")
    readonly_fields = [f.name for f in BreatheSyncRun._meta.fields]
    def has_add_permission(self, request): return False

    def get_urls(self):
        from django.urls import path
        return [path("refresh/", self.admin_site.admin_view(self.refresh),
                     name="rota_breathesyncrun_refresh")] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        last_ok = BreatheSyncRun.objects.filter(ok=True).first()
        last = BreatheSyncRun.objects.first()
        extra = {
            "last_ok": last_ok,
            "last_error": last if (last and not last.ok) else None,
            "unlinked": Clinician.objects.filter(active=True, breathe_employee_id=None).order_by("name"),
            "configured": breathe_client.from_settings() is not None,
        }
        extra.update(extra_context or {})
        return super().changelist_view(request, extra_context=extra)

    def refresh(self, request):
        from django.contrib import messages
        from django.shortcuts import redirect
        from django.utils import timezone
        if request.method != "POST":
            return redirect("admin:rota_breathesyncrun_changelist")
        recent = BreatheSyncRun.objects.filter(
            started__gte=timezone.now() - timedelta(seconds=60)).exists()
        if recent:
            messages.warning(request, "A sync ran less than a minute ago; not running another.")
            return redirect("admin:rota_breathesyncrun_changelist")
        client = breathe_client.from_settings()
        if client is None:
            messages.error(request, "Breathe is not configured (BREATHE_API_KEY unset).")
            return redirect("admin:rota_breathesyncrun_changelist")
        run = breathe_sync.run(client)
        if run.ok:
            messages.success(request, f"Synced: {run.n_deduped} absences, {run.n_unlinked} for unlinked employees.")
        else:
            messages.error(request, f"Sync failed: {run.error}")
        return redirect("admin:rota_breathesyncrun_changelist")
```

Add `from datetime import timedelta` to the module imports if absent.

- [ ] **Step 4: The changelist template**

Create `templates/admin/rota/breathesyncrun/change_list.html`:

```html
{% extends "admin/change_list.html" %}

{% block object-tools-items %}
<li>
  <form method="post" action="{% url 'admin:rota_breathesyncrun_refresh' %}" style="display:inline">
    {% csrf_token %}<button type="submit" class="button"{% if not configured %} disabled title="BREATHE_API_KEY is not set"{% endif %}>Refresh now</button>
  </form>
</li>
{{ block.super }}
{% endblock %}

{% block content %}
<div style="margin: 0 0 16px; padding: 12px 16px; border: 1px solid var(--hairline-color, #ddd); border-radius: 6px;">
  {% if not configured %}
    <p><strong>Breathe is not configured.</strong> Set <code>BREATHE_API_KEY</code> in <code>/etc/rota.env</code> and restart. Until then no leave is read and every clinician is treated as available.</p>
  {% elif last_ok %}
    <p><strong>Last successful sync:</strong> {{ last_ok.started|date:"D j M H:i" }} —
       {{ last_ok.n_deduped }} absence{{ last_ok.n_deduped|pluralize }} from
       {{ last_ok.n_requests }} request{{ last_ok.n_requests|pluralize }},
       {{ last_ok.n_absences }} absence record{{ last_ok.n_absences|pluralize }} and
       {{ last_ok.n_sicknesses }} sickness{{ last_ok.n_sicknesses|pluralize:"es" }};
       {{ last_ok.n_unlinked }} for unlinked employees.</p>
  {% else %}
    <p><strong>No successful sync yet.</strong></p>
  {% endif %}
  {% if last_error %}
    <p style="color: var(--error-fg, #b00)"><strong>Most recent run failed</strong> ({{ last_error.started|date:"D j M H:i" }}): {{ last_error.error }}</p>
  {% endif %}
  {% if unlinked %}
    <p><strong>Not linked to Breathe</strong> — no leave is read for these, so they are always available:
    {% for c in unlinked %}<a href="{% url 'admin:rota_clinician_change' c.pk %}">{{ c.name }}</a>{% if not forloop.last %}, {% endif %}{% endfor %}</p>
  {% endif %}
</div>
{{ block.super }}
{% endblock %}
```

The inline styles use Django admin's own CSS variables with plain fallbacks; this is a stock admin page and outside the tokens rule.

- [ ] **Step 5: The grid warning**

In `rota/views/grid.py`, alongside `is_admin`:

```python
    unlinked_count = (Clinician.objects.filter(active=True, breathe_employee_id=None).count()
                      if is_admin else 0)
```

add `"unlinked_count": unlinked_count` to the context. In `templates/rota/grid.html`, where the toolbar ends and before `.grid-wrap`, add:

```html
{% if unlinked_count %}
<div class="warn">{{ unlinked_count }} clinician{{ unlinked_count|pluralize }} not linked to Breathe — no leave is read for them. <a href="/admin/rota/clinician/?breathe=unlinked">Link them</a>.</div>
{% endif %}
```

`.warn` is the class the day headers already use for their warning strips (`grid.html:32`), so this needs no new CSS. Do not add any.

- [ ] **Step 6: The documentation this task must ship**

Create `docs/admin/breathe.md`:

```markdown
# Leave from Breathe

Leave is not requested or approved in the rota. It is managed in BreatheHR and
read from there — read-only, every fifteen minutes — so that the grid shows who
is off and assisted fill never assigns them.

## Setting it up, in this order

1. **Put the key in the environment.** Add to `/etc/rota.env`:
   ```
   BREATHE_API_KEY=…
   BREATHE_API_URL=https://api.breathehr.com/v1
   ```
   and restart gunicorn. The key never goes in a file in the repository.
2. **Migrate.** `python manage.py migrate`.
3. **Link every clinician.** `/admin/rota/clinician/` — each clinician's
   **Breathe employee** field is a dropdown of your Breathe employees. Pick the
   right one and save. Where a clinician's login email matches a Breathe
   employee's email, that person is pre-selected; you still have to save.
4. **Run the first sync.** `/admin/rota/breathesyncrun/` → **Refresh now**, or
   `python manage.py breathe_sync`.
5. **Enable the timer.** `systemctl enable --now rota-breathe.timer`.

Step 3 before step 4 matters: a sync before anyone is linked reads everything
and stores nothing, reporting every record as "for unlinked employees".

## What counts as off

Three Breathe sources, combined and de-duplicated:

- **Approved leave requests** — holiday, and other leave (maternity, paternity, …).
- **Absences** logged directly by HR.
- **Sickness.** Shown as its own chip. The sickness *type* is never read into
  the rota — only that the person is off.

**Pending requests are not shown.** Leave appears on the rota when Breathe says
it is approved, within fifteen minutes.

## Breathe leave mapping

`/admin/rota/breatheleavemapping/` — how each kind of Breathe record renders.
Holiday → **AL**, sickness → **SICK**, other leave → **OTH** by default; add a
row with a reason name — "Maternity" → MAT — to give a specific reason its own
chip. A reason with no row uses its kind's default.

## The sync status page

`/admin/rota/breathesyncrun/` shows the last successful sync and its counts, the
most recent error if a run failed, and **every clinician not linked to Breathe**.
Unlinked clinicians have no leave read for them and are treated as available;
the week grid warns admins about them too.

**Refresh now** runs a sync immediately — useful the moment leave has just been
approved in Breathe and you want to fill the gap. It refuses if a sync ran in
the last minute.

## If Breathe is down

The rota keeps working from the last successful sync. Nothing blocks on
Breathe. The status page shows the error; the next timer run tries again.

## Breathe absence

`/admin/rota/breatheabsence/` — the rows the sync wrote, read-only. Useful to
check what Breathe actually said about someone. Edit leave in Breathe, not here.
```

In `docs/admin/README.md`, add a row to the pages table — `| [Leave from Breathe](breathe.md) | Linking clinicians, the sync, what counts as off |` — and a troubleshooting row — `| Someone's leave is not on the grid | Are they [linked to Breathe](breathe.md#setting-it-up-in-this-order)? Has a sync run since it was approved? |`.

- [ ] **Step 7: Run everything and commit**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_breathe_status.py tests/test_docs.py tests/test_security.py tests/test_grid_view.py -q
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
git add rota/admin.py templates/admin/rota/breathesyncrun/ rota/views/grid.py templates/rota/grid.html docs/admin/breathe.md docs/admin/README.md tests/test_breathe_status.py
git commit -m "feat: Breathe sync status page, Refresh now, and the unlinked warning

Registers the overlay models in admin — read-only where the sync owns them —
with a changelist header showing the last good run, the last error, and
every clinician nobody has linked. Documented in the same commit, because
an admin screen no page mentions is a setting the practice works out by
trial and error."
```

Expected: green.

---

### Task 11: Deploy units and the remaining documentation

**Files:**
- Create: `deploy/rota-breathe.service`, `deploy/rota-breathe.timer`
- Modify: `deploy/gunicorn.service` (add the two variables to the `/etc/rota.env` comment block)
- Modify: `docs/admin/people.md` (delete "Leave entitlement sessions", lines 97-104; add a "Breathe employee" section), `docs/admin/session-types.md` (delete "Counts toward entitlement", lines 79-97; the Category section's absence bullet drops "offered on the leave request form"), `docs/admin/practice-settings.md` (delete "Leave year start", lines 22-26), `docs/admin/day-to-day.md` (replace the "Leave requests" section, lines 108-126, with two sentences pointing at breathe.md), `README.md` (lines 26 and 29: the setup steps mentioning entitlement and leave year), `docs/backlog.md` (a "Settled" entry)
- Test: `tests/test_breathe_deploy.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_breathe_deploy.py`:

```python
"""The timer that makes the sync run, and the docs that tell an admin how."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_service_runs_the_sync_command_from_the_env_file():
    unit = (ROOT / "deploy" / "rota-breathe.service").read_text()
    assert "breathe_sync" in unit
    assert "EnvironmentFile=/etc/rota.env" in unit, "the key must come from the env file"
    assert "Type=oneshot" in unit


def test_the_timer_fires_every_fifteen_minutes():
    timer = (ROOT / "deploy" / "rota-breathe.timer").read_text()
    assert re.search(r"OnCalendar=.*\*:0/15", timer) or "OnUnitActiveSec=15min" in timer
    assert "WantedBy=timers.target" in timer


def test_the_env_file_comment_names_the_breathe_variables():
    unit = (ROOT / "deploy" / "gunicorn.service").read_text()
    assert "BREATHE_API_KEY" in unit


def test_no_doc_still_describes_local_leave_management():
    docs = "\n".join(p.read_text() for p in (ROOT / "docs" / "admin").glob("*.md"))
    for phrase in ("Leave entitlement sessions", "Counts toward entitlement",
                   "Leave year start", "/admin/rota/leaverequest/"):
        assert phrase not in docs, f"docs still describe {phrase!r}"
    readme = (ROOT / "README.md").read_text()
    assert "counts toward entitlement" not in readme.lower()
    assert "leave year start" not in readme.lower()
```

- [ ] **Step 2: Run and watch them fail**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_breathe_deploy.py -q
```

Expected: FAIL.

- [ ] **Step 3: The units**

Create `deploy/rota-breathe.service`:

```ini
[Unit]
Description=Read leave from BreatheHR into the GP rota
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/root/rota
# BREATHE_API_KEY and BREATHE_API_URL live in the same environment file as
# SECRET_KEY, readable only by root. See gunicorn.service for why.
EnvironmentFile=/etc/rota.env
ExecStart=/root/rota/.venv/bin/python manage.py breathe_sync
```

Create `deploy/rota-breathe.timer`:

```ini
[Unit]
Description=Read leave from BreatheHR every fifteen minutes

[Timer]
OnCalendar=*-*-* *:0/15:00
Persistent=true
RandomizedDelaySec=60

[Install]
WantedBy=timers.target
```

In `deploy/gunicorn.service`, extend the comment block's example env file with:

```
#   BREATHE_API_KEY=…            # from Breathe: Configure > API Settings
#   BREATHE_API_URL=https://api.breathehr.com/v1
```

- [ ] **Step 4: The docs**

- `docs/admin/people.md`: delete the "Leave entitlement sessions" section (line 97 onward). Add, immediately after the "Is trainer" section, where it sat:

  ```markdown
  ### Breathe employee

  Which BreatheHR employee this clinician is. A dropdown of your Breathe
  employees; pick one and save. **Unlinked clinicians have no leave read for
  them and are treated as available** — the sync status page and the week grid
  both warn admins about them. See [Leave from Breathe](breathe.md).
  ```

- `docs/admin/session-types.md`: delete the "Counts toward entitlement" section; in the Category section change the Absence bullet's second sentence to "Absence types are what Breathe leave renders as — see [the mapping](breathe.md#breathe-leave-mapping)."
- `docs/admin/practice-settings.md`: delete the "Leave year start" section.
- `docs/admin/day-to-day.md`: replace the "Leave requests" section with:

  ```markdown
  ## Leave

  Not managed here. Leave is requested and approved in BreatheHR and read into
  the rota every fifteen minutes — see [Leave from Breathe](breathe.md). Swaps
  are still managed here.
  ```

- `README.md`: in the setup steps, remove "counts toward entitlement" from the session-type step and "leave year start" from the practice-settings step; add a step "Link each clinician to their Breathe employee — see docs/admin/breathe.md."
- `docs/backlog.md`, under "Settled": one paragraph dated 2026-09-02 recording that leave moved to Breathe and why the overlay was chosen over rota entries.

- [ ] **Step 5: Run everything and commit**

```bash
SECRET_KEY=throwaway .venv/bin/python -m pytest tests/test_breathe_deploy.py tests/test_docs.py -q
SECRET_KEY=throwaway .venv/bin/python -m pytest -q
SECRET_KEY=throwaway .venv/bin/python manage.py makemigrations --check --dry-run
git add deploy/ docs/ README.md tests/test_breathe_deploy.py
git commit -m "feat: the Breathe sync timer, and docs that no longer describe local leave

A oneshot service on a fifteen-minute timer, reading the key from the same
root-only environment file as SECRET_KEY. Every admin page that described
requesting, approving or counting leave here now points at Breathe instead."
```

Expected: green; "No changes detected".

---

## Self-review

**Spec coverage.** API facts → Tasks 2 and 4 embody them; recorded fixtures are committed. Decisions table: off = union deduped, pending excluded → Task 4; every local feature removed → Task 8; 15-minute sync + Refresh now → Tasks 4, 10, 11; Sick chip to everyone, type never stored → Tasks 3, 4, 5; overlay not entries → Tasks 3, 5; fetch all, filter locally → Task 2; manual linking with email suggestion → Task 9. Model section → Task 3. Client → Task 2. Sync → Task 4. Part-aware resolver and `cell_state` → Task 5. Linking admin → Task 9. Screens: grid/day → Task 5; My Schedule → Task 6; fill → Task 5 (context.py); swaps → Task 7; inbox → Task 8; status page → Task 10; removed screens → Task 8. Documentation → Tasks 10 and 11. Testing section: no network, boundary tests, half-day table, dedup, failed fetch, unlinked, swaps, My Schedule, removal grep → Tasks 1, 2, 4, 5, 6, 7, 8. Deferred items have no task, correctly.

**Deviation from spec, stated in Global Constraints:** two migrations (`0022` add, `0023` remove) rather than one, so every task lands green.

**Placeholder scan.** No TBD/TODO. Every code step carries code. Two steps direct the implementer to read a file before acting (`involved_slots` in Task 7; the inline formset keys in Task 9) — those name what to look for and where, and the assertion that must hold.

**Type consistency.** `Span`, `parts_off(span, day)` — Tasks 1, 3 (`.span` property), 4, 5. `BreatheClient(api_key, base_url, *, opener, timeout)`, `fetch_all(resource)`, `employees()`, `from_settings()` — Tasks 2, 4, 9, 10. `AvailabilityResolver(pattern_rows, clinicians, absences, mapping)` and `leave_type(clinician_id, day, part)` — Tasks 5, 6, 7. `cell_state` key `absence` — Tasks 5, 6. `make_absence(clinician, start, end=None, kind, reason, **half)` — Tasks 5, 6, 7. `BreatheLeaveMapping.as_dict()` — Tasks 3, 5, 6, 7. Admin URL name `rota_breathesyncrun_refresh` — Task 10 in both code and template.

**Ordering constraints.** 1 → 3 (Span). 2 → 4, 9, 10 (client). 3 → 4, 5 (models). 5 → 6, 7 (resolver). 5, 6 → 8 (nothing left reads `LeaveRequest`). 3, 9 → 10 (models registered with their docs; `breathe_employees` loader). 10 → 11 (docs index references `breathe.md`).
