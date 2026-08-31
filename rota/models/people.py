from django.conf import settings
from django.core.exceptions import ValidationError
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
    start_date = models.DateField(
        null=True, blank=True,
        help_text="Do not schedule before this date. Blank means no start bound.")
    end_date = models.DateField(
        null=True, blank=True,
        help_text="Do not schedule after this date. Blank means no end bound.")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError(
                {"end_date": "End date is before the start date."})

    def in_window(self, day):
        """Whether `day` falls inside this clinician's contractual window.

        Separate from `active`, which is the manual override. Both are read
        together by AvailabilityResolver so they cannot drift apart.
        """
        if self.start_date and day < self.start_date:
            return False
        if self.end_date and day > self.end_date:
            return False
        return True
