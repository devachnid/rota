from django.core.exceptions import ValidationError
from django.db import models

from rota import palette
from rota.services.ranges import parse_int_list, validate_int_list


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

    name = models.CharField(
        max_length=100, unique=True,
        help_text="Shown in dropdowns and on the day view.",
    )
    code = models.CharField(
        max_length=8,
        help_text="What the grid cell shows. Keep it short and unique.",
    )
    category = models.CharField(
        max_length=16, choices=Category.choices,
        help_text="Clinical counts toward minimum staffing; Absence marks "
                  "someone as off.",
    )
    colour = models.CharField(
        max_length=32, choices=palette.TINT_CHOICES, default=palette.DEFAULT_TINT,
        help_text="Session tint shown on the grid. All tints are contrast-checked.",
    )
    legacy_colour = models.CharField(
        max_length=7, blank=True, default="",
        help_text="The free-form hex this type used before the palette migration. "
                  "Kept for one release in case a mapping looks wrong.",
    )
    fairness_tracked = models.BooleanField(
        default=False,
        help_text="Shared out pro-rata to contracted sessions and reported "
                  "on the fairness report.",
    )
    pin_on_day_view = models.BooleanField(
        default=False,
        help_text="Show this type in its own block at the top of the day view. "
                  "Use it for the roles someone would open the day view to check "
                  "— Duty above all. Leave it off for the bulk of the rota.",
    )
    allowed_clinicians = models.ManyToManyField(
        "rota.Clinician", blank=True, related_name="restricted_session_types"
    )
    allowed_groups = models.ManyToManyField(
        "rota.ClinicianGroup", blank=True, related_name="restricted_session_types"
    )
    default_site = models.ForeignKey(
        "rota.Site", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
        help_text="Auto-stamped on entries the fill engine creates for this type.",
    )
    blocks_same_day = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="blocked_by_same_day",
        help_text="A clinician holding this type on a day is not auto-assigned "
                  "any of these types the same day.",
    )

    class Meta:
        ordering = ["category", "name"]

    def is_eligible(self, clinician):
        if not self.allowed_clinicians.exists() and not self.allowed_groups.exists():
            return True
        return (
            self.allowed_clinicians.filter(pk=clinician.pk).exists()
            or self.allowed_groups.filter(pk=clinician.group_id).exists()
        )

    @property
    def tint(self):
        """The Tint for this session type, falling back if the key is unknown."""
        return palette.TINTS.get(self.colour) or palette.TINTS[palette.DEFAULT_TINT]

    def __str__(self):
        return self.name


class ClosedDay(models.Model):
    day = models.DateField(
        unique=True,
        help_text="A bank holiday or closure. No sessions are expected "
                  "and no warnings raised.",
    )
    reason = models.CharField(
        max_length=100, blank=True,
        help_text="Shown on the grid header.",
    )

    def __str__(self):
        return f"{self.day} {self.reason}"


class DayNote(models.Model):
    day = models.DateField(unique=True)
    text = models.CharField(
        max_length=300,
        help_text="Shown on the grid header and the day view, to everyone.",
    )

    def __str__(self):
        return f"{self.day}: {self.text}"


class PracticeSettings(models.Model):
    min_clinical_per_session = models.PositiveIntegerField(
        default=2,
        help_text="Warn on the grid when fewer clinical GPs are in for a session.",
    )
    default_fill_session_type = models.ForeignKey(
        SessionType, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="What assisted fill puts in any cell still empty after "
                  "the rules, when you tick that box.",
    )
    open_weekdays = models.CharField(
        max_length=20, default="0,1,2,3,4",
        help_text="The days the surgery is open. The grid shows only these.",
    )
    vts_session_type = models.ForeignKey(
        SessionType, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+", help_text="Leave blank to skip this trainee pass.")
    sdl_session_type = models.ForeignKey(
        SessionType, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+", help_text="Leave blank to skip this trainee pass.")
    mentoring_session_type = models.ForeignKey(
        SessionType, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+", help_text="Leave blank to skip this trainee pass.")

    class Meta:
        verbose_name = "practice settings"
        verbose_name_plural = "practice settings"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def open_weekday_list(self):
        return parse_int_list(self.open_weekdays)

    def clean(self):
        super().clean()
        validate_int_list(self.open_weekdays, 0, 6, "open_weekdays")


class CoverageRule(models.Model):
    class Unit(models.TextChoices):
        PER_SESSION = "SESSION", "Per session"
        PER_DAY = "DAY", "Per full day"
        FULL_DAY_PREFERRED = "DAYPREF", "Full day preferred (splittable)"

    class Frequency(models.TextChoices):
        PER_SLOT = "SLOT", "Per slot"
        PER_WEEK = "WEEK", "Per week"
        PER_MONTH = "MONTH", "Per month (average)"

    session_type = models.ForeignKey(
        SessionType, on_delete=models.CASCADE, related_name="coverage_rules",
        help_text="What must be covered.",
    )
    unit = models.CharField(
        max_length=8, choices=Unit.choices, default=Unit.PER_SESSION,
        help_text="The shape of one placement: a session, a full day, or a "
                  "full day if someone is free for both halves.",
    )
    parts = models.CharField(
        max_length=4, default="BOTH",
        choices=[("AM", "AM"), ("PM", "PM"), ("BOTH", "Both")],
        help_text="Per-session rules only; ignored for full-day rules.",
    )
    weekdays = models.CharField(
        max_length=20, default="0,1,2,3,4",
        help_text="Days this rule applies on.",
    )
    count = models.PositiveIntegerField(
        default=1,
        help_text="How many placements per unit and frequency.",
    )
    priority = models.PositiveIntegerField(default=100, help_text="Lower fills first")
    frequency = models.CharField(
        max_length=6, choices=Frequency.choices, default=Frequency.PER_SLOT,
        help_text="Per slot checks every session; per week and per month "
                  "are quotas the fill engine spreads out.",
    )
    months = models.CharField(
        max_length=40, blank=True, default="",
        help_text="Comma-separated month numbers (1-12); blank = all year",
    )
    preferred_weekdays = models.CharField(
        max_length=20, blank=True, default="",
        help_text="Ordered comma-separated weekday numbers tried first "
                  "(PER_WEEK/PER_MONTH rules), Monday=0",
    )

    class Meta:
        ordering = ["priority", "id"]

    def clean(self):
        super().clean()
        if (self.unit == self.Unit.PER_DAY
                and self.frequency in (self.Frequency.PER_WEEK,
                                       self.Frequency.PER_MONTH)
                and self.count % 2 != 0):
            raise ValidationError(
                "'Per full day' unit requires an even count when frequency "
                "is Per week or Per month (average): each placement "
                "consumes two sessions (AM and PM), so an odd count can "
                "never be satisfied and the rule would silently place "
                "nothing forever."
            )
        validate_int_list(self.months, 1, 12, "months")
        validate_int_list(self.weekdays, 0, 6, "weekdays")
        validate_int_list(self.preferred_weekdays, 0, 6, "preferred_weekdays")

    def applies_on(self, day):
        if self.months:
            if day.month not in parse_int_list(self.months):
                return False
        return day.weekday() in parse_int_list(self.weekdays)

    def preferred_weekday_list(self):
        return parse_int_list(self.preferred_weekdays)

    def parts_for(self):
        return ["AM", "PM"] if self.parts == "BOTH" else [self.parts]

    def __str__(self):
        return f"{self.session_type} x{self.count} ({self.get_unit_display()})"
