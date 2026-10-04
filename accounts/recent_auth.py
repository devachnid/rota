"""When this session last proved who it is — for the actions that must not be
open to anyone who finds a signed-in browser.

Adding a passkey is the one such action. A passkey is a way in that
survives a password change, so a borrowed session — a surgery PC left
signed in — must not be able to add one: it would be a key of the thief's
own, still working after the owner had reset their password and every
other session had been signed out. So a passkey can be added only within
WINDOW of signing in (which covers the "add a passkey" offer shown after a
password login), or after typing the password again.

The mark lives in the session. Signing in by any route stamps it (the
user_logged_in receiver, wired in AccountsConfig.ready), and so does
typing the password again (`confirm_password`).
"""

import time

from django.contrib.auth import authenticate

WINDOW = 10 * 60   # seconds
_KEY = "rota_auth_at"


def mark(request):
    request.session[_KEY] = int(time.time())


def is_recent(request):
    stamped = request.session.get(_KEY)
    return isinstance(stamped, int) and 0 <= time.time() - stamped < WINDOW


def password_allowed(user):
    """Whether this person signs in with a rota password at all. With the
    practice account configured (PRACTICE_HR_URL) only the superuser does;
    everyone else proves who they are on the HR system, so the rota never
    checks their password — not at the login form, not here."""
    from django.conf import settings
    return not settings.PRACTICE_HR_URL or bool(user.is_superuser)


def confirm_password(request, password):
    """Check the signed-in person's password and, if it is right, mark the
    session. Through authenticate(), so a wrong one counts towards the
    login lockout exactly as it would at the login page, and a locked
    account is refused here too."""
    if not isinstance(password, str) or not password:
        return False
    if not password_allowed(request.user):
        return False
    user = authenticate(request, username=request.user.get_username(), password=password)
    if user is None or user.pk != request.user.pk:
        return False
    mark(request)
    return True


def on_login(sender, request, user, **kwargs):
    if request is not None and hasattr(request, "session"):
        mark(request)
