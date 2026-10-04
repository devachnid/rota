from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models

from rota.services.ranges import parse_int_list, validate_int_list


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


class PersonalRequirement(models.Model):
    """Each named clinician does this session type once every N weeks, on
    no fixed day: an aim to fit in, not a fixture. A coverage rule counts
    practice-wide, so one keen GP could satisfy six people's rounds; a
    recurring commitment pins a weekday and drops a missed occurrence.
    The clock — last done, due — lives in rota/services/personal.py, the
    one reader for the fill, the report and the dashboard."""

    PART_CHOICES = [("AM", "AM"), ("PM", "PM"), ("EITHER", "Either")]

    session_type = models.ForeignKey(
        "rota.SessionType", on_delete=models.PROTECT,
        related_name="personal_requirements",
        help_text="What each of them owes.")
    clinicians = models.ManyToManyField(
        "rota.Clinician", related_name="personal_requirements",
        help_text="Who owes it. Each must be eligible for the session type.")
    interval_weeks = models.PositiveSmallIntegerField(
        default=6, help_text="One every this many weeks, per clinician, "
                             "counted from their last one.")
    part = models.CharField(
        max_length=6, choices=PART_CHOICES, default="EITHER",
        help_text="Which half-day it may take.")
    weekdays = models.CharField(
        max_length=20, blank=True, default="",
        help_text="Days it may fall on. Blank means every open day. Monday=0.")
    active_from = models.DateField(
        help_text="A clinician with none yet is due from this date.")
    active_until = models.DateField(
        null=True, blank=True, help_text="Inclusive. Blank means open-ended.")

    class Meta:
        ordering = ["session_type__name", "interval_weeks", "id"]
        verbose_name = "personal requirement"

    def __str__(self):
        return f"{self.session_type.name} every {self.interval_weeks} weeks"

    def clean(self):
        super().clean()
        if self.interval_weeks < 1:
            raise ValidationError({"interval_weeks": "At least one week."})
        validate_int_list(self.weekdays, 0, 6, "weekdays")
        if self.active_until and self.active_until < self.active_from:
            raise ValidationError(
                {"active_until": "Active until is before active from."})

    def live_on(self, day):
        return self.active_from <= day and (
            self.active_until is None or day <= self.active_until)

    def weekday_list(self):
        return parse_int_list(self.weekdays)

    def applies_on(self, day):
        """In force on `day` and on an allowed weekday. Blank weekdays is
        every day; callers restrict to open days."""
        if not self.live_on(day):
            return False
        return not self.weekdays or day.weekday() in self.weekday_list()

    def parts_for(self):
        return ["AM", "PM"] if self.part == "EITHER" else [self.part]
