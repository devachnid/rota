from datetime import timedelta

from django.db import models


class RecurringCommitment(models.Model):
    PART_CHOICES = [("AM", "AM"), ("PM", "PM"), ("BOTH", "Full day")]

    clinician = models.ForeignKey(
        "rota.Clinician", on_delete=models.CASCADE, related_name="commitments")
    session_type = models.ForeignKey(
        "rota.SessionType", on_delete=models.PROTECT, related_name="+")
    weekday = models.PositiveSmallIntegerField(help_text="Monday=0")
    part = models.CharField(max_length=4, choices=PART_CHOICES, default="BOTH")
    site = models.ForeignKey(
        "rota.Site", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+")
    active_from = models.DateField()
    active_until = models.DateField(null=True, blank=True)
    interval_weeks = models.PositiveIntegerField(
        default=1, help_text="1 = weekly, 2 = fortnightly (anchored to the "
                             "week of 'active from')")

    class Meta:
        ordering = ["clinician__name", "weekday", "part"]

    def occurs_on(self, day):
        if day.weekday() != self.weekday:
            return False
        if day < self.active_from:
            return False
        if self.active_until and day > self.active_until:
            return False
        if self.interval_weeks > 1:
            anchor = self.active_from - timedelta(days=self.active_from.weekday())
            week = (day - timedelta(days=day.weekday()) - anchor).days // 7
            if week % self.interval_weeks:
                return False
        return True

    def parts_list(self):
        return ["AM", "PM"] if self.part == "BOTH" else [self.part]

    def __str__(self):
        return (f"{self.clinician.initials} wd{self.weekday} {self.part} "
                f"{self.session_type.code}")
