"""Sign in with the practice account: the HR system is the OpenID Connect
provider.

Who a sign-in is: the HR system's `sub` (its login account's id), once the
rota has seen it. The first time, the `email` claim is matched to an
existing rota user, case-insensitively, and that user's `oidc_sub` is set;
every later sign-in matches on `sub` alone. Matching on email every time
let an HR admin who edited an HR login's email sign in to the rota as
whoever had that email here — a rota admin, or the superuser. So:

- an email match is only offered to a rota user not yet bound to a `sub`;
- a superuser is never signed in this way (the superuser signs in with the
  rota's own password form, which stays for exactly that);
- a new user is created only when no rota user has the email at all, with
  no usable password.

is_rota_admin stays local to the rota and is never set by sign-in."""

from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from .models import User


class PracticeAccountBackend(OIDCAuthenticationBackend):
    def filter_users_by_claims(self, claims):
        sub = str(claims.get("sub") or "")
        email = claims.get("email")
        if sub and User.objects.filter(oidc_sub=sub).exists():
            users = User.objects.filter(oidc_sub=sub)
        elif email:
            users = User.objects.filter(email__iexact=email, oidc_sub="")
        else:
            return User.objects.none()
        return users.exclude(is_superuser=True)

    def create_user(self, claims):
        # Reached when filter_users_by_claims matched nobody. If the email
        # belongs to a rota user all the same, that user is one sign-in may
        # not reach — a superuser, or someone already bound to another
        # sub — and a second account cannot share the address anyway.
        if User.objects.filter(email__iexact=claims["email"]).exists():
            raise SuspiciousOperation("practice-account sign-in refused: the email belongs "
                                      "to a rota account this sign-in may not use")
        user = User(email=claims["email"], oidc_sub=str(claims.get("sub") or ""))
        user.set_unusable_password()
        user.save()
        return user

    def update_user(self, user, claims):
        sub = str(claims.get("sub") or "")
        if sub and not user.oidc_sub:
            user.oidc_sub = sub
            user.save(update_fields=["oidc_sub"])
        return user


def practice_hr_logout_url(request, id_token=None):
    """Where signing out of the rota goes next: the HR system's sign-out
    (django-oauth-toolkit's RP-initiated logout), which ends the session
    there too and sends the browser back to the rota's login page. Without
    it, on a shared PC, the next person to press "Sign in with the practice
    account" was signed straight in as the last one — consent is skipped,
    and the HR session was still open.

    The ID token from sign-in (OIDC_STORE_ID_TOKEN) goes as id_token_hint,
    which lets the HR system sign the person out without asking; a session
    that signed in some other way has none, and HR then asks, as the OIDC
    spec requires. None when the practice account is not configured."""
    if not settings.PRACTICE_HR_URL:
        return None
    params = {
        "post_logout_redirect_uri": request.build_absolute_uri(settings.LOGIN_URL),
        "client_id": settings.OIDC_RP_CLIENT_ID,
    }
    if id_token:
        params["id_token_hint"] = id_token
    return f"{settings.PRACTICE_HR_URL}/o/logout/?{urlencode(params)}"
