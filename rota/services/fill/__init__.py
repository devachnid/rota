from django.db import transaction

from rota.services import entries

from . import commitments, coverage, mentoring, trainees
from .context import FillContext
from .types import FillResult, UnfilledSlot, site_for

__all__ = ["run_fill", "FillResult", "UnfilledSlot"]


@transaction.atomic
def run_fill(actor, start, end, fill_default=False):
    # Its own previous drafts, never a published entry or one an admin
    # placed by hand — the same rule the Delete-drafts card offers as
    # "fill drafts only", and the same function, so there is one rule.
    entries.delete_drafts(actor, start, end, include_manual=False)

    result = FillResult()
    ctx = FillContext(start, end)

    commitments.run(ctx, actor, result)
    trainees.run_vts(ctx, actor, result)
    coverage.run(ctx, actor, result)
    mentoring.run(ctx, actor, result)
    trainees.run_sdl(ctx, actor, result)

    if fill_default:
        default = ctx.settings.default_fill_session_type
        if default:
            for day in ctx.open_days:
                for part in ["AM", "PM"]:
                    for c in ctx.clinicians:
                        if (ctx.available(c.id, day, part)
                                and ctx.is_free(c.id, day, part)
                                and c.id in ctx.eligible_ids(default)):
                            e = entries.assign(actor, c, day, part, default,
                                               site=site_for(default),
                                               manually_set=False,
                                               fill_reason="default fill")
                            ctx.record(e)
                            result.created += 1
    return result
