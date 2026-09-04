"""Getting a password without an admin typing one.

RequestPasswordLinkView is "Forgotten your password?" — public, and so the
one place a link must never be shown on screen. SetPasswordFromLinkView is
where every emailed link lands, invitation or reset: it sets the password
and signs the person in.
"""

import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.signals import user_login_failed
from django.contrib.auth.views import (PasswordChangeView, PasswordResetConfirmView,
                                       PasswordResetView)
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode
from django.views.decorators.http import require_POST

from . import passkeys
from .mail import email_is_configured, send_password_link
from .models import Passkey, User


class RequestPasswordLinkForm(PasswordResetForm):
    """Django's form, with two changes: an account that has never set a
    password (an expired invitation) is included, so it self-heals without
    an admin; and the send goes through send_password_link, throttled.
    Without a relay it does nothing at all — the page reads the same, and
    the link never reaches a public screen."""

    def get_users(self, email):
        return User._default_manager.filter(email__iexact=email, is_active=True)

    def save(self, *args, request=None, **kwargs):
        if not email_is_configured():
            return
        for user in self.get_users(self.cleaned_data["email"]):
            send_password_link(request, user, invite=not user.has_usable_password(),
                               throttle=True)


class RequestPasswordLinkView(PasswordResetView):
    form_class = RequestPasswordLinkForm
    template_name = "registration/password_reset_form.html"
    success_url = reverse_lazy("password_reset_done")


class SetPasswordFromLinkView(PasswordResetConfirmView):
    """Django moves the token from the URL into the session before showing
    the form (reset_url_token), so it never sits in browser history. Only
    active accounts resolve — Django's own get_user does not check — and a
    good link signs the person straight in."""

    template_name = "registration/password_reset_confirm.html"
    post_reset_login = True
    post_reset_login_backend = "django.contrib.auth.backends.ModelBackend"
    success_url = settings.LOGIN_REDIRECT_URL

    def get_user(self, uidb64):
        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            return User._default_manager.get(pk=uid, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist, ValidationError):
            return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_invitation"] = self.user is not None and not self.user.has_usable_password()
        return context


class ChangePasswordView(PasswordChangeView):
    """Signed in and knows the old one. Back to the Account page with a
    word, rather than Django's separate done page."""

    template_name = "registration/password_change_form.html"
    success_url = reverse_lazy("account")

    def form_valid(self, form):
        messages.success(self.request, "Password changed.")
        return super().form_valid(form)


@login_required
def account(request):
    """The person's own page: who they are signed in as, and the things
    only they can do to it — the password, and their passkeys."""
    return render(request, "accounts/account.html",
                  {"passkeys": request.user.passkeys.all()})


def _json_body(request):
    """The JSON object a POST carried, or None if it carried anything else."""
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _credential_from(request):
    """The body's credential dict and name, or (None, None) if the body is
    not the JSON object the page's script sends. Checked here, before the
    service spends the challenge on it."""
    body = _json_body(request)
    if body is None or not isinstance(body.get("credential"), dict):
        return None, None
    if not isinstance(body.get("name", ""), str):
        return None, None
    return body, body["credential"]


@login_required
@require_POST
def passkey_register_options(request):
    return JsonResponse(json.loads(passkeys.registration_options(request, request.user)))


@login_required
@require_POST
def passkey_register(request):
    body, credential = _credential_from(request)
    if credential is None:
        return JsonResponse({"error": "Malformed request."}, status=400)
    try:
        passkey = passkeys.complete_registration(request, request.user, credential,
                                                 body.get("name", ""))
    except passkeys.PasskeyError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"id": passkey.pk, "name": passkey.name})


@login_required
@require_POST
def passkey_remove(request, pk):
    passkey = get_object_or_404(Passkey, pk=pk, user=request.user)
    passkey.delete()
    messages.success(request, f"Passkey “{passkey.name}” removed.")
    return redirect("account")


@require_POST
def passkey_login_options(request):
    return JsonResponse(json.loads(passkeys.login_options(request)))


@require_POST
def passkey_login(request):
    """Possession of the private key, proven, is the whole login: no
    password, no username. axes hears about a bad assertion for a known
    key exactly as it hears about a wrong password."""
    body, credential = _credential_from(request)
    if credential is None:
        return JsonResponse({"error": "Malformed request."}, status=400)
    try:
        passkey = passkeys.verify_login(request, credential)
    except passkeys.PasskeyError as exc:
        known = getattr(exc, "passkey", None)
        if known is not None:
            user_login_failed.send(sender=__name__, credentials={"username": known.user.email},
                                   request=request)
        return JsonResponse({"error": str(exc)}, status=400)
    user = passkey.user
    if not user.is_active:
        return JsonResponse({"error": "This account is not active."}, status=400)
    auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    nxt = body.get("next") or ""
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()},
                                          require_https=request.is_secure()):
        nxt = settings.LOGIN_REDIRECT_URL
    return JsonResponse({"next": nxt})
