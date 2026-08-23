from django.conf import settings
from django.db import models
from django.db.models import Q


class ClinicianGroup(models.Model):
    name = models.CharField(max_length=50, unique=True)
    display_order = models.PositiveIntegerField(default=100)
    min_per_session = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Warn when fewer members of this group are in on a session.",
    )
    is_locum_group = models.BooleanField(default=False)

    class Meta:
        ordering = ["display_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_locum_group"],
                condition=Q(is_locum_group=True),
                name="single_locum_group",
            )
        ]

    def __str__(self):
        return self.name


class Clinician(models.Model):
    name = models.CharField(max_length=100)
    initials = models.CharField(max_length=5)
    group = models.ForeignKey(
        ClinicianGroup, on_delete=models.PROTECT, related_name="clinicians"
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="clinician",
    )
    active = models.BooleanField(default=True)
    is_trainer = models.BooleanField(
        default=False, help_text="May supervise trainee mentoring sessions.")
    leave_entitlement_sessions = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
