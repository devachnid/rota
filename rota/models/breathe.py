"""Leave as read from BreatheHR. Written only by the sync; never by a view.

These rows are an overlay, not rota entries. Putting leave in the entry
table as well as here would be two answers to one question — the failure
the availability consolidation exists to prevent.
"""

from django.db import models

from rota.services.breathe.halfdays import Span


class BreatheAbsence(models.Model):
    class Kind(models.TextChoices):
        HOLIDAY = "holiday", "Holiday"
        OTHER = "other", "Other leave"
        SICKNESS = "sickness", "Sickness"

    clinician = models.ForeignKey(
        "rota.Clinician", on_delete=models.CASCADE, related_name="breathe_absences")
    start_date = models.DateField()
    end_date = models.DateField()
    half_start = models.BooleanField(default=False)
    # am_pm is "AM", "PM" or "" — never null, so two full-day rows (both "")
    # collide on the content key instead of silently bypassing it.
    half_start_am_pm = models.CharField(max_length=2, blank=True, default="")
    half_end = models.BooleanField(default=False)
    half_end_am_pm = models.CharField(max_length=2, blank=True, default="")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    # Breathe's leave_reason name for `other`; blank for holiday; ALWAYS blank
    # for sickness — the sickness type is health data and is discarded by the
    # sync before this row is built, not hidden at render.
    reason = models.CharField(max_length=100, blank=True, default="")
    # Diagnostic: which Breathe ids this row was built from. Comma-separated,
    # because one deduplicated row can come from two endpoints.
    source_ids = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        verbose_name = "Breathe absence"
        constraints = [
            models.UniqueConstraint(
                fields=["clinician", "start_date", "end_date", "half_start",
                        "half_start_am_pm", "half_end", "half_end_am_pm"],
                name="breathe_absence_content_key",
            ),
        ]
        ordering = ["start_date", "clinician_id"]

    @property
    def span(self) -> Span:
        return Span(self.start_date, self.end_date, self.half_start,
                    self.half_start_am_pm, self.half_end, self.half_end_am_pm)

    def __str__(self):
        return f"{self.clinician} {self.kind} {self.start_date}..{self.end_date}"


class BreatheLeaveMapping(models.Model):
    """How a Breathe record becomes a chip: (kind, reason) -> an absence type.
    A blank reason is the kind's default. Resolution: exact, then default."""
    kind = models.CharField(max_length=10, choices=BreatheAbsence.Kind.choices)
    reason = models.CharField(max_length=100, blank=True, default="")
    session_type = models.ForeignKey(
        "rota.SessionType", on_delete=models.PROTECT, related_name="+",
        limit_choices_to={"category": "ABSENCE"})

    class Meta:
        verbose_name = "Breathe leave mapping"
        unique_together = [("kind", "reason")]
        ordering = ["kind", "reason"]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.session_type_id and self.session_type.category != "ABSENCE":
            raise ValidationError({"session_type": "Must be an absence-category type."})

    @classmethod
    def as_dict(cls):
        return {(m.kind, m.reason): m.session_type
                for m in cls.objects.select_related("session_type")}

    def __str__(self):
        return f"{self.kind}/{self.reason or '*'} -> {self.session_type.code}"


class BreatheSyncRun(models.Model):
    started = models.DateTimeField()
    finished = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    n_requests = models.PositiveIntegerField(default=0)
    n_absences = models.PositiveIntegerField(default=0)
    n_sicknesses = models.PositiveIntegerField(default=0)
    n_deduped = models.PositiveIntegerField(default=0)
    n_unlinked = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Breathe sync run"
        ordering = ["-started"]

    def __str__(self):
        state = "ok" if self.ok else "failed"
        return f"{self.started:%Y-%m-%d %H:%M} {state}"
