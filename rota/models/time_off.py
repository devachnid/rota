"""Time off as read from Shift Central. Written only by the sync; never by a view.

These rows are an overlay, not rota entries. Putting leave in the entry
table as well as here would be two answers to one question — the failure
the availability consolidation exists to prevent.
"""

from django.db import models

from rota.services.time_off import Span


class TimeOff(models.Model):
    clinician = models.ForeignKey(
        "rota.Clinician", on_delete=models.CASCADE, related_name="time_off")
    # The span is what Shift Central's first day, last day and part come to
    # in the rota's parts (services/time_off.py). The am_pm fields
    # are "AM", "PM" or "" — never null, so two full-day rows (both "")
    # collide on the content key instead of silently bypassing it.
    start_date = models.DateField()
    end_date = models.DateField()
    half_start = models.BooleanField(default=False)
    half_start_am_pm = models.CharField(max_length=2, blank=True, default="")
    half_end = models.BooleanField(default=False)
    half_end_am_pm = models.CharField(max_length=2, blank=True, default="")
    # The Shift Central leave type's name — the category set up there
    # (Holiday, Sick leave, …). Blank when the record has none. No note on a
    # record is ever read into the rota: it is where someone writes why
    # they are off sick.
    reason = models.CharField(
        max_length=100, blank=True, default="",
        help_text="The Shift Central leave type's name.")
    # Diagnostic: the feed's first_day for the record this row was built
    # from. Comma-separated, because two records covering the same parts
    # deduplicate to one row.
    source_ids = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        verbose_name = "time off"
        verbose_name_plural = "time off"
        constraints = [
            models.UniqueConstraint(
                fields=["clinician", "start_date", "end_date", "half_start",
                        "half_start_am_pm", "half_end", "half_end_am_pm"],
                name="timeoff_content_key",
            ),
        ]
        ordering = ["start_date", "clinician_id"]

    @property
    def span(self) -> Span:
        return Span(self.start_date, self.end_date, self.half_start,
                    self.half_start_am_pm, self.half_end, self.half_end_am_pm)

    def __str__(self):
        return f"{self.clinician} {self.reason or 'time off'} {self.start_date}..{self.end_date}"


class TimeOffMapping(models.Model):
    """How a Shift Central leave type becomes a chip: reason -> an absence type.
    The row with a blank reason is the default. Resolution: exact, then
    default."""
    reason = models.CharField(
        max_length=100, blank=True, default="",
        help_text="The Shift Central leave type exactly as it is named there. Leave "
                  "blank for the default, which any reason without its own row uses.")
    session_type = models.ForeignKey(
        "rota.SessionType", on_delete=models.PROTECT, related_name="+",
        limit_choices_to={"category": "ABSENCE"})

    class Meta:
        verbose_name = "time off mapping"
        verbose_name_plural = "time off mappings"
        ordering = ["reason"]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.session_type_id and self.session_type.category != "ABSENCE":
            raise ValidationError({"session_type": "Must be an absence-category type."})

    @classmethod
    def as_dict(cls):
        return {m.reason: m.session_type
                for m in cls.objects.select_related("session_type")}

    def __str__(self):
        return f"{self.reason or '(default)'} -> {self.session_type.code}"


class TimeOffSyncRun(models.Model):
    started = models.DateTimeField()
    finished = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    n_records = models.PositiveIntegerField(default=0)
    n_matched = models.PositiveIntegerField(default=0)
    n_unmatched = models.PositiveIntegerField(default=0)
    n_outside = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True, default="")
    # Emails of the records nobody here matched: a record value, kept out of
    # `error` and the journal, shown on the status page to the rota's admins.
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Shift Central sync run"
        ordering = ["-started"]

    def __str__(self):
        state = "ok" if self.ok else "failed"
        return f"{self.started:%Y-%m-%d %H:%M} {state}"
