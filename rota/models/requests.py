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
