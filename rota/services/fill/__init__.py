from django.db import transaction

from rota.models import RotaEntry
from rota.services import entries

from . import commitments, coverage, trainees
from .context import FillContext
from .types import FillResult, UnfilledSlot

__all__ = ["run_fill", "FillResult", "UnfilledSlot"]


@transaction.atomic
def run_fill(actor, start, end, fill_default=False):
    RotaEntry.objects.filter(
        day__range=(start, end), is_published=False, manually_set=False
    ).delete()

    result = FillResult()
    ctx = FillContext(start, end)

    commitments.run(ctx, actor, result)
    trainees.run_vts(ctx, actor, result)
    coverage.run(ctx, actor, result)
    trainees.run_sdl(ctx, actor, result)

    if fill_default:
        default = ctx.settings.default_fill_session_type
        if default:
            for day in ctx.open_days:
                for part in ["AM", "PM"]:
                    for c in ctx.clinicians:
                        if (ctx.works_on(c.id, day, part)
                                and ctx.is_free(c.id, day, part)
                                and c.id in ctx.eligible_ids(default)):
                            e = entries.assign(actor, c, day, part, default,
                                               site=default.default_site,
                                               manually_set=False,
                                               fill_reason="default fill")
                            ctx.record(e)
                            result.created += 1
    return result
