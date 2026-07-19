from django.db import models

from .catalog import Part


class PatternSlot(models.Model):
    clinician = models.ForeignKey(
        "rota.Clinician", on_delete=models.CASCADE, related_name="pattern_slots"
    )
    weekday = models.PositiveSmallIntegerField()  # Monday=0
    part = models.CharField(max_length=2, choices=Part.choices)
    works = models.BooleanField(default=True)
    effective_from = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["clinician", "weekday", "part", "effective_from"],
                name="one_pattern_row_per_slot_per_date",
            )
        ]
