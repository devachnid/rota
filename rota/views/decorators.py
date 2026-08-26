from functools import wraps

from django.contrib.auth.views import redirect_to_login
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
    """
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except (KeyError, ValueError) as e:
            return HttpResponse(
                escape(f"Bad request: {e}"),
                status=400,
                content_type="text/plain; charset=utf-8",
            )
    return wrapped
