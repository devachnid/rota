from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse, HttpResponseForbidden


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
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except (KeyError, ValueError) as e:
            return HttpResponse(f"Bad request: {e}", status=400)
    return wrapped
