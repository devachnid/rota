from datetime import timedelta

from rota.models import Clinician
from rota.services import entries

from .scoring import impact_score
from .trainees import _run_trainee_pass
from .types import UnfilledSlot, site_for


def _trainee_free_sessions(ctx, cid, wm, profile):
    """(day, part) pairs this week where the trainee both works and is free,
    restricted to the fill window and the trainee's placement window."""
    out = []
    for i in range(7):
        day = wm + timedelta(days=i)
        if not (ctx.start <= day <= ctx.end
                and profile.placement_start <= day <= profile.placement_end
                and day in ctx.open_day_set):
            continue
        for part in ("AM", "PM"):
            if ctx.available(cid, day, part) and ctx.is_free(cid, day, part):
                out.append((day, part))
    return out


def _trainer_free(ctx, trainer_id, day, part):
    return ctx.available(trainer_id, day, part) and ctx.is_free(trainer_id, day, part)


def run(ctx, actor, result):
    ment = ctx.settings.mentoring_session_type
    if ment is None:
        return

    all_trainers = list(Clinician.objects.filter(active=True, is_trainer=True))

    def make_placer(profile, _weekday, _part):
        cid = profile.clinician_id
        fixed_trainer = profile.trainer
        # Substitutes are only tried once the fixed trainer's own
        # availability check has failed on every session this week (see
        # `if not candidates:` below), so fixed_trainer would fail that
        # identical _trainer_free() check again here too — no need to
        # exclude them from `substitutes` by id as well.
        substitutes = [c for c in all_trainers if c.id != cid]

        def place(wm, need):
            placed_this_week = 0
            while placed_this_week < need:
                trainee_sessions = _trainee_free_sessions(ctx, cid, wm, profile)

                candidates = []
                if fixed_trainer is not None:
                    for day, part in trainee_sessions:
                        if _trainer_free(ctx, fixed_trainer.id, day, part):
                            candidates.append((0, day, part, fixed_trainer))

                if not candidates:
                    for day, part in trainee_sessions:
                        for sub in substitutes:
                            if _trainer_free(ctx, sub.id, day, part):
                                candidates.append((1, day, part, sub))
                                break  # one trainer per session is enough

                if not candidates:
                    break  # Stop trying to place; will report shortfalls below

                candidates.sort(key=lambda c: (c[0], -impact_score(ctx, c[1], c[2]),
                                               c[1], c[2]))
                _, day, part, trainer = candidates[0]
                e1, e2 = entries.assign_pair(
                    actor, day, part, profile.clinician, trainer, ment,
                    site=site_for(ment), manually_set=False,
                    fill_reason="mentoring")
                ctx.record(e1)
                ctx.record(e2)
                result.created += 2
                placed_this_week += 1

            # Report each unplaced session
            reason = ("no trainer available" if fixed_trainer is None
                      else "no session with trainer free")
            for _ in range(need - placed_this_week):
                result.unfilled.append(UnfilledSlot(wm, None, "Mentoring", reason))
            return placed_this_week
        return place

    _run_trainee_pass(ctx, actor, result, ment, "mentoring",
                      extra_skip=lambda weekday, part: False,
                      make_placer=make_placer)
