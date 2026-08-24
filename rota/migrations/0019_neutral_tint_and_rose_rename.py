"""Add a true neutral tint, and rename the family that was pretending to be one.

The palette had no grey. Every one of its 40 tints was a colour, because the
generator built them all from a hue ring — and the family sitting at 360
degrees was named "slate", which promises a grey and rendered #ffe2ec, a pale
pink. DEFAULT_TINT pointed at it, so a session type with no colour chosen, and
any pre-palette grey the original mapping could not place, silently became pink.

Two changes, and they are separate on purpose:

  - `slate-*` becomes `rose-*`. Same colour, honest name. This is a pure
    rename: the tint renders identically before and after.
  - A real neutral pair is generated outside the hue ring and becomes the new
    DEFAULT_TINT.

Rows are only rewritten if they actually hold a slate key, so this is safe to
re-run and safe on a fresh install where nothing does. Rows already sitting on
some other tint are untouched — nothing here re-points a deliberate choice at
the new default.
"""

from django.db import migrations, models

from rota import palette

_RENAMES = {"slate-soft": "rose-soft", "slate-strong": "rose-strong"}


def _remap(apps, mapping):
    SessionType = apps.get_model("rota", "SessionType")
    for old, new in mapping.items():
        SessionType.objects.filter(colour=old).update(colour=new)


def slate_to_rose(apps, schema_editor):
    _remap(apps, _RENAMES)


def rose_to_slate(apps, schema_editor):
    _remap(apps, {new: old for old, new in _RENAMES.items()})


class Migration(migrations.Migration):

    dependencies = [("rota", "0018_alter_traineeprofile_trainer")]

    operations = [
        migrations.RunPython(slate_to_rose, rose_to_slate),
        migrations.AlterField(
            model_name="sessiontype",
            name="colour",
            field=models.CharField(
                max_length=32,
                choices=palette.TINT_CHOICES,
                default=palette.DEFAULT_TINT,
                help_text="Session tint shown on the grid. All tints are "
                          "contrast-checked.",
            ),
        ),
    ]
