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
from urllib.parse import urlencode, urlparse

from django.conf import settings

log = logging.getLogger("rota.breathe")

EMPLOYEE_FIELDS = ("id", "first_name", "last_name", "email", "employee_ref",
                   "status", "leaving_date")

PER_PAGE = 100
# A practice-scale account is a handful of pages at per_page=100. A Link
# header that points at its own page — or round a cycle — would otherwise
# spend the rate limit and hang the request that started it.
MAX_PAGES = 200
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

    def _same_origin(self, url):
        """Whether `url` is on exactly the scheme and host the client was
        configured for.

        A string prefix is not a host test. With a pathless base — which
        BREATHE_API_URL invites and rstrip("/") produces — both
        `https://api.breathehr.com.evil.example/v1/x` and
        `https://api.breathehr.com@evil.example/v1/x` start with
        "https://api.breathehr.com". netloc is the whole authority, so the
        userinfo trick fails on it too.
        """
        base, other = urlparse(self.base_url), urlparse(url)
        return (base.scheme, base.netloc) == (other.scheme, other.netloc)

    # -- every page --------------------------------------------------------

    def fetch_all(self, resource):
        """Every row of `resource`, following Link: rel="next" to the end.

        No date filters: /absences filters by overlap and /leave_requests by
        start date, so a windowed fetch would silently miss leave that began
        before the window. Practice-scale data makes the full fetch cheap.
        """
        url = f"{self.base_url}/{resource}?{urlencode({'per_page': PER_PAGE})}"
        rows = []
        pages = 0
        while url:
            pages += 1
            if pages > MAX_PAGES:
                log.warning("breathe /%s: more than %s pages; stopped",
                            resource, MAX_PAGES)
                raise BreatheError(
                    f"Breathe returned more than {MAX_PAGES} pages for /{resource}",
                    path=f"/{resource}")
            data, headers = self._get(url)
            page = data.get(resource, [])
            rows.extend(page)
            m = _NEXT.search(headers.get("link", ""))
            next_url = m.group(1) if (m and page) else None
            if next_url and not self._same_origin(next_url):
                # A Link header is attacker-reachable — from Breathe, or from
                # anything on the path to it. Following it would attach the
                # real X-API-KEY header to a request to whatever host it
                # names, so this is checked before that request is ever made.
                bad_path = urlparse(next_url).path
                log.warning("breathe %s -> Link named another host; refused", bad_path)
                raise BreatheError(
                    "Breathe returned a Link to another host; refusing to follow it",
                    path=bad_path)
            url = next_url
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
