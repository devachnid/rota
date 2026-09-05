"""Two htmx endpoints behind the Feedback control: the form, and the send.
Both render partials into #modal (templates/base.html) with no {% extends %},
the same shape as the grid's cell and note forms."""

from datetime import timedelta
from urllib.parse import urlsplit

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import FeedbackForm
from .mail import notify_admins
from .models import Feedback

HOURLY_LIMIT = 10
TOO_MANY = "That's a lot of feedback in one hour — please try again later."


def _page(request):
    """The path and query the reporter was looking at. htmx sends the page's
    URL as HX-Current-URL on every request; only our own host counts, and
    the result is cut to the column."""
    url = request.headers.get("HX-Current-URL", "")
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.netloc.lower() != request.get_host().lower():
        return ""
    page = parts.path + (f"?{parts.query}" if parts.query else "")
    return page[:300]


@login_required
def feedback_form(request):
    return render(request, "feedback/_form.html", {"form": FeedbackForm()})


@login_required
@require_POST
def feedback_send(request):
    form = FeedbackForm(request.POST)
    # Errors come back as the form again at 200: htmx 2 leaves a 4xx out of
    # the target, and the modal is where the reporter is looking.
    if not form.is_valid():
        return render(request, "feedback/_form.html", {"form": form})
    since = timezone.now() - timedelta(hours=1)
    recent = Feedback.objects.filter(reporter=request.user, created_at__gte=since).count()
    if recent >= HOURLY_LIMIT:
        form.add_error(None, TOO_MANY)
        return render(request, "feedback/_form.html", {"form": form})
    feedback = Feedback.objects.create(
        kind=form.cleaned_data["kind"],
        message=form.cleaned_data["message"],
        viewport=form.cleaned_data["viewport"],
        page=_page(request),
        user_agent=request.headers.get("User-Agent", "")[:300],
        reporter=request.user,
    )
    # Saved first: whatever the relay does, the report exists and the admin
    # list shows it.
    notify_admins(request, feedback)
    return render(request, "feedback/_sent.html",
                  {"feedback": feedback, "email": request.user.email})
