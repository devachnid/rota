import hmac
import logging
import time
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from accounts.client_ip import client_ip

log = logging.getLogger("rota.api")


def _valid(token):
    """Whether the token is one of ROTA_API_TOKENS. Every configured token is
    compared, in constant time, so the time taken says nothing about which
    of them a guess was close to. Bytes, because compare_digest refuses a
    str with a non-ASCII character in it."""
    given = token.encode()
    matched = False
    for known in settings.ROTA_API_TOKENS:
        matched |= hmac.compare_digest(given, known.encode())
    return matched


def _over_limit(request):
    """None while this address is within API_RATE_LIMIT_PER_MINUTE, else the
    429 to send. A fixed one-minute window per address, counted for every
    request, so a guessed token costs as much as a good one. The setting is
    read now, not at import, and 0 switches the limit off. The warning is
    logged once per window per address, not per request."""
    limit = settings.API_RATE_LIMIT_PER_MINUTE
    if limit <= 0:
        return None
    now = time.time()
    minute = int(now // 60)
    address = client_ip(request) or "unknown"
    key = f"api-rate:{address}:{minute}"
    cache.add(key, 0, timeout=60)
    try:
        count = cache.incr(key)
    except ValueError:  # the key expired between add and incr: this is the window's first request
        cache.add(key, 1, timeout=60)
        count = 1
    if count <= limit:
        return None
    if cache.add(f"api-rate-warned:{address}:{minute}", 1, timeout=60):
        log.warning("API rate limit reached: %s", address)
    response = JsonResponse({"error": "too many requests"}, status=429)
    response["Retry-After"] = str(max(1, int((minute + 1) * 60 - now)))
    return response


def token_required(view):
    """Only a request with `Authorization: Bearer <token>`, the token one of
    ROTA_API_TOKENS, reaches the view. No session, no CSRF: the rota is a
    server, not a signed-in person, so the view is exempt from
    CsrfViewMiddleware (nothing here reads the session or a cookie) and a
    wrong-method request reaches the JSON 405 rather than Django's CSRF page.
    The scheme is case-insensitive (RFC 7235). With no tokens configured nothing gets
    in. The refusal names no reason, and neither it nor anything here logs
    the header (config.middleware.RequestLogMiddleware logs the request line,
    without a query string or headers). Only GET, after the token: anything
    else is a JSON 405, not Django's HTML one.

    Before the token is looked at, each request counts against a per-address
    limit (API_RATE_LIMIT_PER_MINUTE), so guessing a token is slowed too.

    Every response leaves as `Cache-Control: no-store`: this is people's
    names, their addresses and when they are away."""
    @csrf_exempt
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        response = _over_limit(request)
        if response is not None:
            response["Cache-Control"] = "no-store"
            return response
        header = request.headers.get("Authorization", "")
        token = header[len("Bearer "):] if header[:7].lower() == "bearer " else ""
        if token and _valid(token):
            if request.method == "GET":
                response = view(request, *args, **kwargs)
            else:
                response = JsonResponse({"error": "method not allowed"}, status=405)
                response["Allow"] = "GET"
        else:
            log.warning("API request refused: %s %s", request.method, request.path)
            response = JsonResponse({"error": "unauthorised"}, status=401)
            response["WWW-Authenticate"] = "Bearer"
        response["Cache-Control"] = "no-store"
        return response
    return wrapped
