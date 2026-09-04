"""Every email the app sends leaves through here: an invitation to set a
password, or a link to reset one. Both carry the same link — Django's reset
token, single-use and expiring — with different words around it.

Mailjet is the relay on staging, and it rewrites links for click-tracking
unless told not to: a password link that arrives as an mjt.lu redirect
looks like phishing and hands a third party the click. The two headers
below turn that off per message; they are inert on any other relay.
"""

import smtplib
from datetime import timedelta
from typing import NamedTuple

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

RESEND_WAIT = timedelta(minutes=5)
TRACKING_OFF = {"X-Mailjet-TrackClick": "0", "X-Mailjet-TrackOpen": "0"}


class LinkToCopy(NamedTuple):
    """What send_password_link returns when the email did not go: the link
    for an admin to pass on by hand, and why — "" when email is not
    configured, the relay's own error otherwise."""
    link: str
    reason: str


def email_is_configured():
    """The one test the app uses. EMAIL_HOST is "" unless /etc/rota.env
    names a relay (config/settings.py)."""
    return bool(settings.EMAIL_HOST)


def link_expires(sent_at):
    return sent_at + timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT)


def password_link(request, user):
    """Absolute, from the request — right behind the tunnel (https, via
    SECURE_PROXY_SSL_HEADER) and on a dev box (http) alike."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    path = reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token})
    return request.build_absolute_uri(path)


def send_password_link(request, user, *, invite, throttle=False):
    """Mint a link for `user` and email it.

    Returns None when the email went. Returns a LinkToCopy when it could not
    go — email not configured, or the relay refused — so an admin can pass
    the link on by hand. With throttle=True (the public reset form), a link
    handed out in the last RESEND_WAIT means this call does nothing and
    returns None: the page says the same thing either way.

    password_link_sent_at is stamped whenever a link is handed out, sent or
    shown; the admin's state field and the throttle read it. The token does
    not depend on the stamp, so stamping never invalidates a link.
    """
    if (throttle and user.password_link_sent_at is not None
            and timezone.now() - user.password_link_sent_at < RESEND_WAIT):
        return None
    requester = request.user
    now = timezone.now()
    link = password_link(request, user)
    context = {
        "link": link,
        "expires": link_expires(now),
        "email": user.email,
        # Who to ask for another: the admin who sent it. A signed-in GP
        # using the public form for a colleague is not that person.
        "contact": (requester.email if requester.is_authenticated
                    and (requester.is_rota_admin or requester.is_superuser) else None),
    }
    kind = "invitation" if invite else "password_reset"
    subject = "".join(render_to_string(f"registration/{kind}_subject.txt", context).splitlines())
    body = render_to_string(f"registration/{kind}_email.txt", context)
    user.password_link_sent_at = now
    user.save(update_fields=["password_link_sent_at"])
    if not email_is_configured():
        return LinkToCopy(link, "")
    message = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email],
                           headers=TRACKING_OFF)
    try:
        message.send(fail_silently=False)
    except (smtplib.SMTPException, OSError) as exc:
        return LinkToCopy(link, str(exc) or exc.__class__.__name__)
    return None
