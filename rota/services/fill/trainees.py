import math
from datetime import timedelta

from rota.models import RotaEntry, TraineeProfile
from rota.services import entries

from .accrual import due_through, week_monday
from .scoring import impact_score
from .types import UnfilledSlot, site_for


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


def _seed_weekly_done(ctx, profile, session_type, anchor, weeks):
    """Existing (already-on-the-rota-before-this-pass) sessions of this
    type for this trainee, split into a pre-window running total plus a
    per-week bucket for entries dated inside the fill window.

    A hand-booked entry sitting in a *later* week must not suppress a
    placement in an *earlier* week: seeding `done` once from the whole
    [anchor, ctx.end] range up front (as a single scalar) does exactly
    that, since a week-4 entry counts against week 1's need too. Instead,
    return the pre-window count (everything strictly before `weeks[0]` —
    always "done" from week one onward, mirroring the pre-window half of
    coverage.py's _boundary_existing_counts) separately from a per-week
    dict, so the caller can add each week's own bucket to the running
    `done` total only once its loop reaches that week — i.e. "up to and
    including this week", not the entire range.

    One query covers the whole span; entries this pass places itself are
    NOT included here (they're added via the caller's own `done += 1`
    after each placement) so nothing is double-counted.
    """
    first_week = weeks[0] if weeks else None
    pre_window = 0
    by_week = {}
    days = RotaEntry.objects.filter(
        clinician=profile.clinician, session_type=session_type,
        day__gte=anchor, day__lte=ctx.end,
    ).values_list("day", flat=True)
    for day in days:
        wk = week_monday(day)
        if first_week is not None and wk < first_week:
            pre_window += 1
        else:
            by_week[wk] = by_week.get(wk, 0) + 1
    return pre_window, by_week


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
        weeks = ctx.weeks()
        done, existing_by_week = _seed_weekly_done(ctx, profile, vts, anchor, weeks)
        cid = profile.clinician_id
        for wm in weeks:
            done += existing_by_week.get(wm, 0)
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
                    site=site_for(vts), manually_set=False,
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
        weeks = ctx.weeks()
        done, existing_by_week = _seed_weekly_done(ctx, profile, sdl, anchor, weeks)
        cid = profile.clinician_id
        for wm in weeks:
            done += existing_by_week.get(wm, 0)
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
                    site=site_for(sdl), manually_set=False,
                    fill_reason="SDL")
                ctx.record(entry)
                result.created += 1
                done += 1
            # Report each unplaced session
            for _ in range(need - placed):
                result.unfilled.append(UnfilledSlot(
                    wm, None, "SDL", "no free session"))
