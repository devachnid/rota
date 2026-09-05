"""A bug report or an idea from someone using the rota, and what the admins
did about it. The app writes the top half; the admin writes the bottom.

No IP address: the reporter is signed in, so it would add nothing."""

from django.conf import settings
from django.db import models
from django.utils import timezone

# Plain string keys, not Kind members: Enum hashes by name, and a dict keyed
# on members would work today only because name and value coincide.
KIND_WORDS = {"BUG": "bug report", "IDEA": "idea"}


class Feedback(models.Model):
    class Kind(models.TextChoices):
        BUG = "BUG", "Something's wrong"
        IDEA = "IDEA", "An idea"

    class Status(models.TextChoices):
        NEW = "NEW", "New"
        SEEN = "SEEN", "Seen"
        DONE = "DONE", "Done"

    # What the reporter said, and what the app saw — read-only in the admin.
    kind = models.CharField(max_length=4, choices=Kind.choices)
    message = models.TextField()
    page = models.CharField(
        max_length=300, blank=True,
        help_text="Path and query of the page the report was sent from.")
    viewport = models.CharField(max_length=20, blank=True, help_text="Width x height in CSS pixels.")
    user_agent = models.CharField(max_length=300, blank=True)
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="feedback")
    created_at = models.DateTimeField(auto_now_add=True)

    # Triage and the reply — the admin's half.
    status = models.CharField(max_length=4, choices=Status.choices, default=Status.NEW)
    admin_note = models.TextField(blank=True, help_text="For admins only — never sent.")
    reply = models.TextField(blank=True, help_text="Sent to the reporter by Send reply.")
    replied_at = models.DateTimeField(null=True, blank=True)
    replied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "feedback"
        verbose_name_plural = "feedback"

    @property
    def kind_word(self):
        """'bug report' or 'idea' — the noun the emails and the thanks use.
        The choice labels are sentences, so they do not read in prose."""
        return KIND_WORDS[self.kind]

    def __str__(self):
        who = self.reporter.email if self.reporter_id else "someone who has left"
        when = f" on {timezone.localdate(self.created_at):%-d %b %Y}" if self.created_at else ""
        return f"{self.kind_word.capitalize()} from {who}{when}"
