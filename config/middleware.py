import logging
import re
import time

from django.utils.cache import add_never_cache_headers

from accounts.client_ip import client_ip

access_log = logging.getLogger("rota.access")

# A password link's path is the credential until it is used: /reset/<uid>/<token>/.
_RESET_TOKEN = re.compile(r"^(/accounts/reset/)[^/]+/[^/]+/")


class RequestLogMiddleware:
    """One line per request to the journal: who (Cloudflare's address for
    them, and the account if signed in), what, and how it ended. Behind the
    tunnel gunicorn only ever sees 127.0.0.1, and Django logs nothing about
    ordinary requests, so without this there is no record to look back at
    after an incident.

    The path is logged without its query string, and a password link's
    token is replaced: the log must not become a place to collect working
    links from. Static files never reach here (WhiteNoise sits above)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.monotonic()
        response = self.get_response(request)
        user = getattr(request, "user", None)
        who = f"user={user.pk}" if user is not None and user.is_authenticated else "anon"
        path = _RESET_TOKEN.sub(r"\1<redacted>/", request.path)
        access_log.info("%s %s %s %s %s %dms", client_ip(request) or "-", who,
                        request.method, path, response.status_code,
                        (time.monotonic() - started) * 1000)
        return response


class PrivatePagesMiddleware:
    """Signed-in pages are not kept by the browser, and signing out clears
    what it kept.

    The rota is used on shared surgery PCs. A page served with no
    Cache-Control could be shown again from the back button or history after
    the person who opened it had signed out: their schedule, their swap
    messages, the Account page with their email. So every response to a
    signed-in request gets Django's never-cache headers (no-store, private)
    unless the view set its own policy — sw.js and the manifest do. Static
    files never reach here: WhiteNoise answers them earlier in the stack.

    Signing out — the app's logout or the admin's — adds Clear-Site-Data:
    "cache", so a copy stored before this change, or by a browser that kept
    one anyway, goes too. Sits after AuthenticationMiddleware, which gives
    it request.user.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        signed_in = request.user.is_authenticated
        response = self.get_response(request)
        if signed_in and not response.has_header("Cache-Control"):
            add_never_cache_headers(response)
        if signed_in and not request.user.is_authenticated:
            response["Clear-Site-Data"] = '"cache"'
        return response
