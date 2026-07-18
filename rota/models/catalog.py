from django.db import models


class Part(models.TextChoices):
    AM = "AM", "AM"
    PM = "PM", "PM"


class Site(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class SessionType(models.Model):
    class Category(models.TextChoices):
        CLINICAL = "CLINICAL", "Clinical"
        NON_CLINICAL = "NON_CLINICAL", "Non-clinical"
        ABSENCE = "ABSENCE", "Absence"

    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=8)
    category = models.CharField(max_length=16, choices=Category.choices)
    colour = models.CharField(max_length=7, default="#8ecae6")
    fairness_tracked = models.BooleanField(default=False)
    counts_toward_entitlement = models.BooleanField(default=False)
    allowed_clinicians = models.ManyToManyField(
        "rota.Clinician", blank=True, related_name="restricted_session_types"
    )
    allowed_groups = models.ManyToManyField(
        "rota.ClinicianGroup", blank=True, related_name="restricted_session_types"
    )

    def is_eligible(self, clinician):
        if not self.allowed_clinicians.exists() and not self.allowed_groups.exists():
            return True
        return (
            self.allowed_clinicians.filter(pk=clinician.pk).exists()
            or self.allowed_groups.filter(pk=clinician.group_id).exists()
        )

    def __str__(self):
        return self.name
