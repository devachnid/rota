from django.conf import settings
from django.db import models

from .catalog import Part


class LocumRequirement(models.Model):
    class Status(models.TextChoices):
        POSSIBLE = "POSSIBLE", "Possibly needed"
        # Approval to seek a locum, before advertising — Tom, 2026-09-03.
        # The value stays inside max_length=10.
        APPROVED = "APPROVED", "Need approved"
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
    covering = models.ForeignKey(
        "rota.Clinician", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
        help_text="The clinician this locum stands in for.",
    )
    rota_entry = models.OneToOneField(
        "rota.RotaEntry", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="locum_requirement",
    )

    class Meta:
        ordering = ["day", "part"]

    def __str__(self):
        return f"Locum {self.day} {self.part} ({self.get_status_display()})"


class SwapRequest(models.Model):
    class Status(models.TextChoices):
        PROPOSED = "PROPOSED", "Awaiting colleague"
        ACCEPTED = "ACCEPTED", "Awaiting admin"
        APPROVED = "APPROVED", "Applied"
        DECLINED = "DECLINED", "Declined"

    proposer = models.ForeignKey(
        "rota.Clinician", on_delete=models.CASCADE, related_name="swaps_proposed"
    )
    proposer_day = models.DateField()
    proposer_part = models.CharField(max_length=2, choices=Part.choices)
    colleague = models.ForeignKey(
        "rota.Clinician", on_delete=models.CASCADE, related_name="swaps_received"
    )
    colleague_day = models.DateField()
    colleague_part = models.CharField(max_length=2, choices=Part.choices)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices,
                              default=Status.PROPOSED)
    admin_comment = models.TextField(blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
