"""Getting a password without an admin typing one.

RequestPasswordLinkView is "Forgotten your password?" — public, and so the
one place a link must never be shown on screen. SetPasswordFromLinkView is
where every emailed link lands, invitation or reset: it sets the password
and signs the person in.
"""

from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetView
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy
from django.utils.http import urlsafe_base64_decode

from .mail import email_is_configured, send_password_link
from .models import User


class RequestPasswordLinkForm(PasswordResetForm):
    """Django's form, with two changes: an account that has never set a
    password (an expired invitation) is included, so it self-heals without
    an admin; and the send goes through send_password_link, throttled.
    Without a relay it does nothing at all — the page reads the same, and
    the link never reaches a public screen."""

    def get_users(self, email):
        return User._default_manager.filter(email__iexact=email, is_active=True)

    def save(self, request=None, **kwargs):
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
