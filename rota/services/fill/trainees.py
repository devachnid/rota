import math
from datetime import timedelta

from rota.models import RotaEntry, TraineeProfile
from rota.services import entries

from .accrual import due_through, week_monday
from .scoring import impact_score
from .types import UnfilledSlot


def _profiles(ctx):
    return (TraineeProfile.objects
            .filter(clinician__active=True,
                    placement_start__lte=ctx.end,
                    placement_end__gte=ctx.start)
            .select_related("clinician", "trainer"))


def _anchor(profile):
    """Monday of the week accrual starts counting from: normally placement
    start, but requirements_tracked_from lets an in-progress placement be
    onboarded onto a fresh install without the trainee immediately owing
    every session since day one (Finding A). Never earlier than placement
    start."""
    return week_monday(max(profile.placement_start,
                           profile.requirements_tracked_from
                           or profile.placement_start))


def _existing_count(ctx, profile, session_type, anchor):
    """Sessions of this type already on the rota for this trainee, from
    `anchor` through ctx.end (Finding B): a DB query for the portion before
    ctx.start (not covered by ctx's own prefetch) plus ctx's already-loaded
    count for [ctx.start, ctx.end], which mirrors coverage.py's
    _boundary_existing_counts and also picks up entries placed earlier in
    this same pass via ctx.record() — without querying for them twice.
    """
    pre_window = 0
    if anchor < ctx.start:
        pre_window = RotaEntry.objects.filter(
            clinician=profile.clinician, session_type=session_type,
            day__gte=anchor, day__lt=ctx.start,
        ).count()
    return pre_window + ctx.clinician_type_count(profile.clinician_id,
                                                  session_type.id)


def _capped_need(rate, due, done):
    """Cumulative due minus done, clamped so a trainee is never asked to
    catch up more than one week's entitlement plus one extra session in a
    single week (Finding A2) — genuine backlog drains gradually instead of
    landing in one burst."""
    return min(due - done, math.ceil(rate) + 1)


def run_vts(ctx, actor, result):
    vts = ctx.settings.vts_session_type
    if vts is None:
        return
    for profile in _profiles(ctx):
        rate, weekday, part = profile.weekly_rates()["vts"]
        if rate == 0 or weekday is None:
            continue
        anchor = _anchor(profile)
        done = _existing_count(ctx, profile, vts, anchor)
        cid = profile.clinician_id
        for wm in ctx.weeks():
            need = _capped_need(rate, due_through(rate, anchor, wm), done)
            if need < 1:
                continue
            day = wm + timedelta(days=weekday)
            if not (ctx.start <= day <= ctx.end
                    and profile.placement_start <= day <= profile.placement_end
                    and day in ctx.open_day_set):
                continue
            if ctx.works_on(cid, day, part) and ctx.is_free(cid, day, part):
                entry = entries.assign(
                    actor, profile.clinician, day, part, vts,
                    site=vts.default_site, manually_set=False,
                    fill_reason="VTS")
                ctx.record(entry)
                result.created += 1
                done += 1
            else:
                result.unfilled.append(UnfilledSlot(
                    day, part, "VTS", "anchored slot unavailable"))


def run_sdl(ctx, actor, result):
    sdl = ctx.settings.sdl_session_type
    if sdl is None:
        return
    for profile in _profiles(ctx):
        rate, _weekday, _part = profile.weekly_rates()["sdl"]
        if rate == 0:
            continue
        anchor = _anchor(profile)
        done = _existing_count(ctx, profile, sdl, anchor)
        cid = profile.clinician_id
        for wm in ctx.weeks():
            need = _capped_need(rate, due_through(rate, anchor, wm), done)
            if need < 1:
                continue
            candidates = []
            for i in range(7):
                day = wm + timedelta(days=i)
                if not (ctx.start <= day <= ctx.end
                        and profile.placement_start <= day <= profile.placement_end
                        and day in ctx.open_day_set):
                    continue
                for part in ("AM", "PM"):
                    if ctx.works_on(cid, day, part) and ctx.is_free(cid, day, part):
                        candidates.append((day, part))
            candidates.sort(key=lambda dp: (-impact_score(ctx, dp[0], dp[1]), dp[0], dp[1]))
            placed = min(need, len(candidates))
            for day, part in candidates[:placed]:
                entry = entries.assign(
                    actor, profile.clinician, day, part, sdl,
                    site=sdl.default_site, manually_set=False,
                    fill_reason="SDL")
                ctx.record(entry)
                result.created += 1
                done += 1
            # Report each unplaced session
            for _ in range(need - placed):
                result.unfilled.append(UnfilledSlot(
                    wm, None, "SDL", "no free session"))
