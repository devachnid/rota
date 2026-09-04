from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class ClinicianGroup(models.Model):
    name = models.CharField(
        max_length=50, unique=True,
        help_text="Partners, Salaried, GPST, Locums …",
    )
    display_order = models.PositiveIntegerField(
        default=100,
        help_text="Groups appear on the grid in this order, lowest first.",
    )
    min_per_session = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Warn when fewer members of this group are in on a session.",
    )
    is_locum_group = models.BooleanField(
        default=False,
        help_text="Exactly one group: locums appear on the grid only in "
                  "weeks they hold a session.",
    )

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
    name = models.CharField(
        max_length=100,
        help_text="Full name, as it appears on the day view and reports.",
    )
    initials = models.CharField(
        max_length=5,
        help_text="Up to five characters — what the week grid shows.",
    )
    group = models.ForeignKey(
        ClinicianGroup, on_delete=models.PROTECT, related_name="clinicians",
        help_text="Orders the grid and drives the group staffing warning.",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="clinician",
        help_text="The login account for this clinician, if they have one.",
    )
    active = models.BooleanField(
        default=True,
        help_text="Untick to remove someone from every eligibility pool "
                  "while keeping their history — the alternative to deleting.",
    )
    is_trainer = models.BooleanField(
        default=False, help_text="May supervise trainee mentoring sessions.")
    start_date = models.DateField(
        null=True, blank=True,
        help_text="Do not schedule before this date. Blank means no start bound.")
    end_date = models.DateField(
        null=True, blank=True,
        help_text="Do not schedule after this date. Blank means no end bound.")
    # The Breathe employee this clinician is. Linked by hand in admin (a
    # dropdown of employees); unique so two clinicians can never share one
    # person's leave; nullable because a locum or a new starter may have no
    # Breathe record yet. Unlinked clinicians have no leave and are treated
    # as available — surfaced as an admin warning, not hidden.
    breathe_employee_id = models.PositiveIntegerField(null=True, blank=True, unique=True)

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
