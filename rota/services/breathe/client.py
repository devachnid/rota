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
