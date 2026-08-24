"""Recompute `colour` from `legacy_colour` after the nearest_tint hue fix.

0015 mapped every free-text hex onto a palette key using `palette.nearest_tint`.
That version of the function never compared hue angles — it scored hue families
by squared sRGB distance to the tint backgrounds, and since every background
sits at OKLCH L~0.94 or 0.88 the score was dominated by lightness. Hue barely
registered. The practice's `Duty` session, #eb4034, came out as `amber-strong`:
a pale orange one step from `Annual Leave`.

Fixing the function does not fix data already written, so this migration
replays the mapping with the corrected one. The original hex survives in
`legacy_colour`, which is the only reason the repair is possible at all.

Only rows with a non-empty `legacy_colour` are touched. An empty one means
either that 0015 skipped the row (it already held a tint key) or that the row
was created afterwards — in both cases the current `colour` was chosen
deliberately and guessing at it would be a second unasked-for rewrite.

Idempotent: `nearest_tint` is a pure function of `legacy_colour`, and this
migration never writes to `legacy_colour`, so a second run recomputes exactly
the same keys. On a fresh install 0015 already used the corrected function and
this is a no-op.
"""

from django.db import migrations

from rota import palette


def repair(apps, schema_editor):
    SessionType = apps.get_model("rota", "SessionType")
    for st in SessionType.objects.exclude(legacy_colour=""):
        corrected = palette.nearest_tint(st.legacy_colour)
        if corrected != st.colour:
            st.colour = corrected
            st.save(update_fields=["colour"])


def unrepair(apps, schema_editor):
    """Deliberately a no-op, and reversible without losing anything.

    The state this replaced was produced by a function that no longer exists;
    reproducing it would mean re-implementing the bug in order to write wrong
    data back. Nothing is lost by declining: `legacy_colour` is the source of
    truth here and this migration never touches it, so reversing on past 0015
    still restores each row's original hex exactly as it always did.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('rota', '0015_map_legacy_colours'),
    ]

    operations = [migrations.RunPython(repair, unrepair)]
