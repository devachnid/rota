from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseForbidden
from django.utils.html import escape


def admin_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.is_rota_admin:
            return HttpResponseForbidden()
        return view(request, *args, **kwargs)
    return wrapped


def parse_errors_as_400(view):
    """Turn a parsing failure into a 400 rather than a 500.

    The message is served as **plain text and escaped**. Both matter, and the
    reason is a real reflected-XSS bug this used to have: Python puts the
    offending value into the exception message, so
    `date.fromisoformat("<img src=x onerror=...>")` raises
    `Invalid isoformat string: '<img src=x onerror=...>'`, and the old version
    returned that straight into an HTML response with no escaping. Several of
    the views wrapped here take path segments on GET — `/rota/daynote/<day>/`
    among them — so it was reachable by sending a logged-in admin a link, with
    no CSRF token to get in the way.

    text/plain stops the browser parsing it as markup (X-Content-Type-Options:
    nosniff, which Django sets by default, stops it sniffing back to HTML).
    The escape is belt and braces: it keeps the response safe if anyone later
    changes the content type back.

    ValidationError is caught alongside KeyError and ValueError because the
    range parser (rota.services.ranges) raises it, and it is neither of the
    other two: `CoverageRule.applies_on()` and
    `PracticeSettings.open_weekday_list()` both parse stored text at read
    time, so a value that ever slipped past `clean()` turned what used to be
    a 400 naming the offending value into a bare 500. Its messages are the
    same shape — they quote the value — so they get the same escaping.
    """
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ValidationError as e:
            # ValidationError's own str() is the repr of a list. messages
            # renders each one with its params interpolated, which is what
            # makes the response name the value that failed.
            return _bad_request("; ".join(e.messages))
        except (KeyError, ValueError) as e:
            return _bad_request(f"Bad request: {e}")
    return wrapped


def _bad_request(message):
    return HttpResponse(
        escape(message),
        status=400,
        content_type="text/plain; charset=utf-8",
    )
