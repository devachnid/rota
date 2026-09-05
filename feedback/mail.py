"""The two emails feedback sends: a notification to the people who maintain
the app when a report arrives, and an admin's reply to the reporter. Both
leave through the same door as the password links — same sender, same
relay rule, Mailjet's tracking off — and neither may raise into a page: the
report is saved before anything here runs, and a relay failure goes to the
journal."""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from accounts.mail import TRACKING_OFF, email_is_configured

logger = logging.getLogger(__name__)


def recipients():
    """Who is told about a new report: every active superuser with an email.
    Superusers are the developer role here; rota admins run the practice."""
    User = get_user_model()
    return list(User.objects.filter(is_superuser=True, is_active=True)
                .exclude(email="").order_by("email").values_list("email", flat=True))


def _who(feedback):
    return feedback.reporter.email if feedback.reporter_id else "someone who has left"


def notify_admins(request, feedback):
    """Email the maintainers about a saved report. True when a message left;
    False when there was nobody to tell, no relay, or the relay refused —
    the admin list shows the report regardless."""
    to = recipients()
    if not to or not email_is_configured():
        return False
    subject = f"[Rota] {feedback.kind_word.capitalize()} from {_who(feedback)}"
    context = {
        "feedback": feedback,
        "who": _who(feedback),
        "created": timezone.localtime(feedback.created_at),
        "admin_link": request.build_absolute_uri(
            reverse("admin:feedback_feedback_change", args=[feedback.pk])),
    }
    body = render_to_string("feedback/notify_email.txt", context)
    message = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, to, headers=TRACKING_OFF)
    try:
        message.send(fail_silently=False)
    except Exception:  # noqa: BLE001 — the report is saved; the failure is the journal's
        logger.exception("feedback notification for #%s could not be sent", feedback.pk)
        return False
    return True


def send_reply(request, feedback):
    """Email `feedback.reply` to the reporter, Reply-To the admin sending it.
    None when it went; otherwise a short reason for the admin to read.
    Stamps nothing — the admin action does that, and only on None."""
    if not feedback.reporter_id or not feedback.reporter.email:
        return "The reporter's account is gone"
    if not email_is_configured():
        return "Email isn't set up"
    quoted = "\n".join("> " + line for line in feedback.message.splitlines()) or ">"
    context = {
        "reply": feedback.reply,
        "admin_email": request.user.email,
        "created": timezone.localtime(feedback.created_at),
        "page": feedback.page,
        "quoted": quoted,
    }
    subject = f"Reply to your rota {feedback.kind_word}"
    body = render_to_string("feedback/reply_email.txt", context)
    message = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL,
                           [feedback.reporter.email], headers=TRACKING_OFF,
                           reply_to=[request.user.email])
    try:
        message.send(fail_silently=False)
    except Exception as exc:  # noqa: BLE001 — see notify_admins
        logger.exception("feedback reply for #%s could not be sent", feedback.pk)
        return str(exc) or exc.__class__.__name__
    return None
