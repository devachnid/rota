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


class ClosedDay(models.Model):
    day = models.DateField(unique=True)
    reason = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return f"{self.day} {self.reason}"


class DayNote(models.Model):
    day = models.DateField(unique=True)
    text = models.CharField(max_length=300)

    def __str__(self):
        return f"{self.day}: {self.text}"


class PracticeSettings(models.Model):
    min_clinical_per_session = models.PositiveIntegerField(default=2)
    leave_year_start_month = models.PositiveIntegerField(default=4)
    leave_year_start_day = models.PositiveIntegerField(default=1)
    default_fill_session_type = models.ForeignKey(
        SessionType, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    open_weekdays = models.CharField(
        max_length=20, default="0,1,2,3,4", help_text="Comma-separated, Monday=0"
    )

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def open_weekday_list(self):
        return [int(x) for x in self.open_weekdays.split(",") if x != ""]


class CoverageRule(models.Model):
    class Unit(models.TextChoices):
        PER_SESSION = "SESSION", "Per session"
        PER_DAY = "DAY", "Per full day"

    session_type = models.ForeignKey(
        SessionType, on_delete=models.CASCADE, related_name="coverage_rules"
    )
    unit = models.CharField(max_length=8, choices=Unit.choices, default=Unit.PER_SESSION)
    parts = models.CharField(
        max_length=4, default="BOTH",
        choices=[("AM", "AM"), ("PM", "PM"), ("BOTH", "Both")],
        help_text="Per-session rules only; ignored for full-day rules.",
    )
    weekdays = models.CharField(max_length=20, default="0,1,2,3,4")
    count = models.PositiveIntegerField(default=1)
    priority = models.PositiveIntegerField(default=100, help_text="Lower fills first")

    class Meta:
        ordering = ["priority", "id"]

    def applies_on(self, day):
        return day.weekday() in [int(x) for x in self.weekdays.split(",") if x != ""]

    def parts_for(self):
        return ["AM", "PM"] if self.parts == "BOTH" else [self.parts]

    def __str__(self):
        return f"{self.session_type} x{self.count} ({self.get_unit_display()})"
