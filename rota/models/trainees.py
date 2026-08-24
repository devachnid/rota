from django.db import models

from .catalog import Part


class TraineeStageRule(models.Model):
    class Stage(models.TextChoices):
        FY2 = "FY2", "FY2"
        ST1 = "ST1", "ST1"
        ST2 = "ST2", "ST2"
        ST3 = "ST3", "ST3"

    stage = models.CharField(max_length=3, choices=Stage.choices, unique=True)
    vts_per_week = models.DecimalField(max_digits=4, decimal_places=2, default=1)
    sdl_per_week = models.DecimalField(max_digits=4, decimal_places=2, default=1)
    mentoring_per_week = models.DecimalField(max_digits=4, decimal_places=2,
                                             default=1)
    vts_weekday = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Monday=0; blank = VTS not anchored")
    vts_part = models.CharField(max_length=2, choices=Part.choices,
                                null=True, blank=True)

    class Meta:
        ordering = ["stage"]

    def __str__(self):
        return self.stage


class TraineeProfile(models.Model):
    clinician = models.OneToOneField(
        "rota.Clinician", on_delete=models.CASCADE,
        related_name="trainee_profile")
    stage = models.CharField(max_length=3, choices=TraineeStageRule.Stage.choices)
    wte_percent = models.PositiveIntegerField(default=100)
    trainer = models.ForeignKey(
        "rota.Clinician", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="trainees",
        limit_choices_to={"is_trainer": True},
        help_text="The trainee's named trainer for the placement. Only "
                  "clinicians flagged as trainers are offered; when the "
                  "named trainer is away the fill engine substitutes "
                  "another trainer automatically.")
    placement_start = models.DateField()
    placement_end = models.DateField()
    requirements_tracked_from = models.DateField(
        null=True, blank=True,
        help_text="Requirements accrue from this date rather than placement "
                  "start — set when the rota system starts tracking an "
                  "in-progress placement. Blank means accrue from placement "
                  "start.")

    def stage_rule(self, rules=None):
        """The seeded TraineeStageRule for this trainee's stage, or None if
        an admin has deleted the row (the four rows are reference data,
        seeded by migration, but nothing at the DB level stops deletion —
        callers must treat None as "no rates due", not a fatal error).

        `rules` is an optional {stage: TraineeStageRule} mapping for callers
        that already hold them all — the trainee report and every trainee
        fill pass iterate profiles, and without it each iteration costs a
        query. A mapping with no entry for this stage yields None, which is
        the same answer a deleted row gives, so the caller needs no special
        case for the two.
        """
        if rules is not None:
            return rules.get(self.stage)
        return TraineeStageRule.objects.filter(stage=self.stage).first()

    def weekly_rates(self, rules=None):
        rule = self.stage_rule(rules)
        if rule is None:
            return {
                "vts": (0.0, None, None),
                "sdl": (0.0, None, None),
                "mentoring": (0.0, None, None),
            }
        f = self.wte_percent / 100
        return {
            "vts": (float(rule.vts_per_week) * f, rule.vts_weekday, rule.vts_part),
            "sdl": (float(rule.sdl_per_week) * f, None, None),
            "mentoring": (float(rule.mentoring_per_week) * f, None, None),
        }

    def __str__(self):
        return f"{self.clinician.name} ({self.stage} {self.wte_percent}%)"
