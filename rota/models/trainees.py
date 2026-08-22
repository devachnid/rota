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
        related_name="trainees")
    placement_start = models.DateField()
    placement_end = models.DateField()

    def stage_rule(self):
        return TraineeStageRule.objects.get(stage=self.stage)

    def weekly_rates(self):
        rule = self.stage_rule()
        f = self.wte_percent / 100
        return {
            "vts": (float(rule.vts_per_week) * f, rule.vts_weekday, rule.vts_part),
            "sdl": (float(rule.sdl_per_week) * f, None, None),
            "mentoring": (float(rule.mentoring_per_week) * f, None, None),
        }

    def __str__(self):
        return f"{self.clinician.name} ({self.stage} {self.wte_percent}%)"
