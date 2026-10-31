"""A read-only client for Shift Central's GP leave feed, on the standard
library: https only outside DEBUG, no redirects, the token never logged,
the body never logged."""

import json
import logging
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlparse

from django.conf import settings

log = logging.getLogger("rota.shift_central")


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_RefuseRedirects)


class ShiftCentralError(Exception):
    pass


class ShiftCentralClient:
    def __init__(self, base_url, token, *, opener=None, timeout=10):
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._open = opener or (lambda req: _OPENER.open(req, timeout=timeout))

    def leave(self, start, end):
        url = f"{self.base_url}/api/v1/leave?" + urlencode({"from": start.isoformat(), "to": end.isoformat()})
        if urlparse(url).scheme != "https" and not settings.DEBUG:
            raise ShiftCentralError("SHIFT_CENTRAL_URL is not https; the token was not sent")
        req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json", "Authorization": f"Bearer {self._token}"})
        try:
            with self._open(req) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            log.warning("shift central leave -> %s", e.code)
            raise ShiftCentralError(f"Shift Central returned {e.code} for leave") from None
        except (urllib.error.URLError, OSError) as e:
            log.warning("shift central unreachable: %s", e.__class__.__name__)
            raise ShiftCentralError("Shift Central unreachable") from None
        try:
            body = json.loads(raw)
        except ValueError:
            raise ShiftCentralError("Shift Central returned a non-JSON body for leave") from None
        if not isinstance(body, dict) or not isinstance(body.get("leave"), list):
            raise ShiftCentralError("Shift Central's leave response has no 'leave' list")
        return body


def from_settings():
    if not settings.SHIFT_CENTRAL_URL or not settings.SHIFT_CENTRAL_TOKEN:
        return None
    return ShiftCentralClient(settings.SHIFT_CENTRAL_URL, settings.SHIFT_CENTRAL_TOKEN)
