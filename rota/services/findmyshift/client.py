"""A read-only client for the FindMyShift API (v1.4), on the standard library.

What the developer portal (findmyshift.co.uk/developers) documents, and
what this is built on:

  - Every method accepts GET or POST; parameters go as a query string, a
    form body or JSON. The key is a parameter named `apiKey`. It is sent
    here as a form field in a POST body, never in the URL, so it cannot
    land in an access log or a referrer.
  - One request at a time per key, and 429 on breach. The sync is
    sequential by construction and does not retry a 429.
  - `teams/list`, `staff/list` (all teams when no teamId) and
    `time-off/list` (teamId, optional staffId, from, to). No pagination is
    documented and none is handled: a practice is one list.
  - Staff records carry date of birth, phone numbers, pay rates and
    salaries. They are projected to STAFF_FIELDS the moment the response
    is parsed and nothing else is ever held — not in a cache, not in a log.

What the portal does not document is the shape of a response: field names,
the date format, whether a list comes bare or wrapped. The client asks for
JSON and returns whatever list it finds; the sync reads fields by name
with alternatives, and `findmyshift_sync --inspect` prints the names a real
account actually sends. The client never logs a response body or the key.
Errors carry the method, the status and the start of a plain-text error
body, which is how FindMyShift reports a bad key or a missing parameter.
"""

import json
import logging
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlparse

from django.conf import settings

log = logging.getLogger("rota.findmyshift")

# Measured against a real account (2026-10-23): a staff record's id is
# `staffId`, a team's is `teamId`, and a team carries the account's
# time-off types as `timeOffTypes` (each with `timeOffTypeId` and
# `description`). Names in STAFF_FIELDS are FindMyShift's own; `id` is
# filled from `staffId` so callers have one name for it.
STAFF_FIELDS = ("id", "staffId", "firstName", "lastName", "displayName", "emailAddress",
                "dateStarted", "dateFinished", "active", "payrollId", "teamId")
# The keys a list may come wrapped under. A bare JSON array needs none.
LIST_KEYS = ("results", "data", "items", "timeOff", "staff", "teams")
ERROR_BODY_CHARS = 160


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """urllib's own redirect handler re-sends the request — the form body
    with the key in it, or a GET without it — to whatever host and scheme
    the Location names, plain http too. Nothing FindMyShift serves needs a
    redirect. Returning None leaves the 3xx as an HTTPError, which _post
    turns into a FindMyShiftError."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_RefuseRedirects)


class FindMyShiftError(Exception):
    def __init__(self, message, *, status=None, method=""):
        super().__init__(message)
        self.status = status
        self.method = method


class FindMyShiftClient:
    def __init__(self, api_key, base_url="https://www.findmyshift.co.uk/api/1.4", *,
                 opener=None, timeout=30):
        self._key = api_key
        self.base_url = base_url.rstrip("/")
        self._open = opener or (lambda req: _OPENER.open(req, timeout=timeout))

    # -- one call ----------------------------------------------------------

    def call(self, method, **params):
        """One API method, as parsed JSON. `params` are the documented
        arguments; None values are left out."""
        url = f"{self.base_url}/{method}"
        if urlparse(url).scheme != "https":
            # The key reads every staff member's record and all their time
            # off. It does not travel in the clear, whatever
            # FINDMYSHIFT_API_URL says (rota.E007 flags the setting itself
            # at deploy time).
            log.warning("findmyshift %s: not https; key not sent", method)
            raise FindMyShiftError("FINDMYSHIFT_API_URL is not https; the key was not sent",
                                   method=method)
        body = {"apiKey": self._key}
        body.update({k: v for k, v in params.items() if v is not None})
        req = urllib.request.Request(
            url, data=urlencode(body).encode(), method="POST",
            headers={"Accept": "application/json",
                     "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with self._open(req) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = self._error_detail(e)
            log.warning("findmyshift %s -> %s", method, e.code)
            if 300 <= e.code < 400:
                raise FindMyShiftError(
                    f"FindMyShift redirected {method} ({e.code}); not followed",
                    status=e.code, method=method) from None
            raise FindMyShiftError(f"FindMyShift returned {e.code} for {method}{detail}",
                                   status=e.code, method=method) from None
        except (urllib.error.URLError, OSError) as e:
            log.warning("findmyshift %s unreachable: %s", method, e.__class__.__name__)
            raise FindMyShiftError(f"FindMyShift unreachable for {method}",
                                   method=method) from None
        try:
            return json.loads(raw)
        except ValueError:
            log.warning("findmyshift %s returned a non-JSON body", method)
            raise FindMyShiftError(f"FindMyShift returned a non-JSON body for {method}",
                                   method=method) from None

    def _error_detail(self, e):
        """The start of a plain-text error body — "401: No authentication
        parameters found…" is FindMyShift's way of saying what went wrong.
        The key is struck out of it in case the body echoes a parameter."""
        try:
            text = e.read(ERROR_BODY_CHARS + 1).decode("utf-8", "replace")
        except Exception:
            return ""
        text = " ".join(text.split())
        if not text:
            return ""
        if self._key:
            text = text.replace(self._key, "[FINDMYSHIFT_API_KEY]")
        if len(text) > ERROR_BODY_CHARS:
            text = text[:ERROR_BODY_CHARS] + "…"
        return f": {text}"

    # -- lists -------------------------------------------------------------

    def rows(self, method, **params):
        """A list method's rows, whether the API sends a bare array or an
        object wrapping one. An empty object is an empty list."""
        data = self.call(method, **params)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in LIST_KEYS:
                if isinstance(data.get(key), list):
                    return data[key]
            lists = [v for v in data.values() if isinstance(v, list)]
            if len(lists) == 1:
                return lists[0]
            if not data:
                return []
        raise FindMyShiftError(
            f"FindMyShift returned no list for {method} (top-level "
            f"{type(data).__name__}" + (f" with keys {sorted(data)[:8]}" if isinstance(data, dict) else "")
            + ")", method=method)

    def teams(self):
        return self.rows("teams/list")

    def time_off(self, team_id, since, until):
        """Every time-off record the key can see for `team_id` between two
        dates, inclusive, as the API sent them."""
        return self.rows("time-off/list", teamId=team_id,
                         **{"from": since.isoformat(), "to": until.isoformat()})

    def staff(self, team_id=None):
        """Staff, projected. This is the only place the raw record exists in
        memory, and it does not leave this function."""
        out = []
        for s in self.rows("staff/list", teamId=team_id or None):
            if not isinstance(s, dict):
                continue
            row = {k: s.get(k) for k in STAFF_FIELDS}
            row["id"] = s.get("staffId", s.get("id"))
            out.append(row)
        return out


def from_settings():
    """A client from settings, or None when the integration is off."""
    if not settings.FINDMYSHIFT_API_KEY:
        return None
    return FindMyShiftClient(settings.FINDMYSHIFT_API_KEY, settings.FINDMYSHIFT_API_URL)
