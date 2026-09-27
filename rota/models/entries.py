from django.conf import settings
from django.db import models

from .catalog import Part


class RotaEntry(models.Model):
    day = models.DateField()
    part = models.CharField(max_length=2, choices=Part.choices)
    clinician = models.ForeignKey(
        "rota.Clinician", on_delete=models.PROTECT, related_name="rota_entries"
    )
    session_type = models.ForeignKey(
        "rota.SessionType", on_delete=models.PROTECT, related_name="rota_entries"
    )
    site = models.ForeignKey(
        "rota.Site", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.CharField(max_length=200, blank=True)
    is_published = models.BooleanField(default=False)
    manually_set = models.BooleanField(default=False)
    allocation_group = models.UUIDField(null=True, blank=True)
    companion_group = models.UUIDField(
        null=True, blank=True,
        help_text="Links the two clinicians' entries of a paired session "
                  "(e.g. mentoring). Distinct from allocation_group.",
    )
    fill_reason = models.CharField(max_length=200, blank=True)
    # Keyed into the clinical system's appointment screen: when, and by
    # whom. Set from the grid's ticking mode; cleared by anything that
    # changes what the session is (services/entries.assign on a type or
    # site change, either kind of swap). A timestamp, not a boolean, so the
    # tooltip can say when.
    entered_at = models.DateTimeField(null=True, blank=True)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["day", "part", "clinician"], name="one_entry_per_cell"
            )
        ]
        ordering = ["day", "part"]
        verbose_name = "rota entry"
        verbose_name_plural = "rota entries"

    def __str__(self):
        return f"{self.clinician.initials} {self.day} {self.part} {self.session_type.code}"


class RotaEntryLog(models.Model):
    day = models.DateField()
    part = models.CharField(max_length=2, blank=True)
    clinician_name = models.CharField(max_length=100, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Who, as text: the login's email when the row was written. The foreign
    # key goes to NULL if that login is ever deleted, and a trail that
    # forgets who did things once their account is gone is not one — so the
    # name is kept alongside, the way clinician_name is.
    actor_name = models.CharField(max_length=254, blank=True)
    action = models.CharField(max_length=20)
    detail = models.CharField(max_length=200, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at"]
        verbose_name = "audit log entry"
        verbose_name_plural = "audit log"

    def save(self, *args, **kwargs):
        if self.actor_id and not self.actor_name:
            self.actor_name = self.actor.get_username()
        super().save(*args, **kwargs)
