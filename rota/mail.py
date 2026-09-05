"""The emails swaps send, so nobody has to keep checking My schedule: the
colleague when asked, the proposer when answered, the admins when a swap
awaits their approval, and both GPs when an admin decides.

Same door as the password links and feedback — same sender, the relay's
tracking off — and none of it may raise into a page: the swap is saved
before anything here runs, and a relay failure goes to the journal. A GP
with no linked account or no email address is skipped; the swap still
happens.
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.template.loader import render_to_string

from accounts.mail import TRACKING_OFF, email_is_configured
from rota.models import SwapRequest
from rota.services import swaps as swaps_svc

logger = logging.getLogger(__name__)


def _email(clinician):
    """The clinician's login email, or None when they have no account."""
    if not clinician.user_id or not clinician.user.email:
        return None
    return clinician.user.email


def admin_emails():
    """Every active rota admin with an email — the people who approve."""
    User = get_user_model()
    return list(User.objects.filter(is_active=True, is_rota_admin=True)
                .exclude(email="").order_by("email").values_list("email", flat=True))


def summary(req):
    """What the swap does, for the body of every message: describe() while
    the rota fits a pattern, the two sessions side by side when it no
    longer does."""
    return swaps_svc.describe(req) or (
        f"{req.proposer.name}'s {swaps_svc.when(req.proposer_day, req.proposer_part)} "
        f"for {req.colleague.name}'s {swaps_svc.when(req.colleague_day, req.colleague_part)}.")


def _quoted(text):
    return "\n".join("> " + line for line in text.splitlines()) or ">"


def _send(request, req, to, subject, template, *, reply_to=None, what=None, **extra):
    """One message. True when it left; False when there was nobody to send
    to, no relay, or the relay refused."""
    to = [address for address in to if address]
    if not to or not email_is_configured():
        return False
    # Everything from here is inside the guard, not just the send: a
    # template or rendering error would otherwise reach the page — and in
    # the admin, roll back the decision the action had just applied.
    try:
        context = {
            "req": req,
            "what": what or summary(req),
            "message_quoted": _quoted(req.message),
            "my_schedule": request.build_absolute_uri("/me/"),
            "requests": request.build_absolute_uri("/requests/"),
            **extra,
        }
        body = render_to_string(f"rota/email/{template}.txt", context)
        message = EmailMessage(f"[Rota] {subject}", body, settings.DEFAULT_FROM_EMAIL, to,
                               headers=TRACKING_OFF,
                               reply_to=[reply_to] if reply_to else None)
        message.send(fail_silently=False)
    except Exception:  # noqa: BLE001 — the swap is saved; the failure is the journal's
        logger.exception("swap email %s for #%s could not be sent", template, req.pk)
        return False
    return True


def swap_proposed(request, req):
    """To the colleague: who, what, the message, where to answer. Reply-To
    the proposer so a question goes straight back to them."""
    return _send(request, req, [_email(req.colleague)],
                 f"{req.proposer.name} would like to swap a session with you",
                 "swap_proposed", reply_to=_email(req.proposer))


def swap_accepted(request, req):
    """To the proposer (it is with the admins now) and to every rota admin
    (it needs their approval — with the problems, if the rota has moved
    since it was proposed). How many messages left."""
    sent = _send(request, req, [_email(req.proposer)],
                 f"{req.colleague.name} accepted your swap — awaiting admin approval",
                 "swap_accepted", reply_to=_email(req.colleague))
    sent += _send(request, req, admin_emails(),
                  f"Swap awaiting your approval: {req.proposer.name} and {req.colleague.name}",
                  "swap_awaiting_admin", problems=swaps_svc.validate(req))
    return int(sent)


def swap_declined_by_colleague(request, req):
    return _send(request, req, [_email(req.proposer)],
                 f"{req.colleague.name} declined your swap",
                 "swap_declined_by_colleague", reply_to=_email(req.colleague),
                 comment_quoted=_quoted(req.colleague_comment))


def swap_decided(request, req, *, what=None):
    """To both GPs once an admin has applied or declined it. `what` is the
    describe() sentence captured before applying: once a PEOPLE swap has
    moved the entries, the rota no longer reads as that swap."""
    applied = req.status == SwapRequest.Status.APPROVED
    pair = f"{req.proposer.name} and {req.colleague.name}"
    return _send(request, req, [_email(req.proposer), _email(req.colleague)],
                 f"Swap applied: {pair}" if applied else f"Swap declined: {pair}",
                 "swap_applied" if applied else "swap_declined_by_admin",
                 reply_to=request.user.email or None, what=what,
                 admin=request.user.email, comment_quoted=_quoted(req.admin_comment))
