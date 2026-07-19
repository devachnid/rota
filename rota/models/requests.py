from django.conf import settings
from django.db import models

from .catalog import Part


class LocumRequirement(models.Model):
    class Status(models.TextChoices):
        POSSIBLE = "POSSIBLE", "Possibly needed"
        ADVERTISED = "ADVERTISED", "Advertised"
        BOOKED = "BOOKED", "Booked"

    day = models.DateField()
    part = models.CharField(max_length=2, choices=Part.choices)
    session_type = models.ForeignKey(
        "rota.SessionType", on_delete=models.PROTECT, related_name="+"
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.POSSIBLE
    )
    details = models.TextField(blank=True)
    clinician = models.ForeignKey(
        "rota.Clinician", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="locum_bookings",
    )
    rota_entry = models.OneToOneField(
        "rota.RotaEntry", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="locum_requirement",
    )

    class Meta:
        ordering = ["day", "part"]

    def __str__(self):
        return f"Locum {self.day} {self.part} ({self.get_status_display()})"


class LeaveRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        DECLINED = "DECLINED", "Declined"

    clinician = models.ForeignKey(
        "rota.Clinician", on_delete=models.CASCADE, related_name="leave_requests"
    )
    session_type = models.ForeignKey(
        "rota.SessionType", on_delete=models.PROTECT, related_name="+",
        limit_choices_to={"category": "ABSENCE"},
    )
    start_date = models.DateField()
    end_date = models.DateField()
    message = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.PENDING)
    admin_comment = models.TextField(blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
