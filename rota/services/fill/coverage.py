from datetime import date, timedelta

from rota.models import CoverageRule, RotaEntry
from rota.services import entries, fairness

from . import accrual
from .types import UnfilledSlot

WINDOW_DAYS = 91


def _eligible(ctx, cid, day, parts, st):
    return (
        all(ctx.works_on(cid, day, p) for p in parts)
        and all(ctx.is_free(cid, day, p) for p in parts)
        and cid in ctx.eligible_ids(st)
        and not ctx.blocked(cid, day, st)
        and not (st.fairness_tracked
                 and any(tid in ctx.fairness_type_ids
                         for tid in ctx.day_type_ids(cid, day)))
    )


class _FairnessState:
    """Mutable fairness/rotation bookkeeping shared by _pick() across a
    single rule's placements (PER_SLOT or quota)."""

    __slots__ = ("actuals", "last", "total_assigned", "total_weight")

    def __init__(self, actuals, last, total_assigned, total_weight):
        self.actuals = actuals
        self.last = last
        self.total_assigned = total_assigned
        self.total_weight = total_weight

    def record(self, cid, day, n):
        self.actuals[cid] = self.actuals.get(cid, 0) + n
        self.total_assigned += n
        self.last[cid] = day


def _pick(ctx, cands, st, fairness_state):
    """Choose a clinician from `cands`: fairness deficit first for
    fairness-tracked types, else longest-since rotation. Shared by the
    PER_SLOT loop and the quota (PER_WEEK/PER_MONTH) placement helpers so
    the two paths never drift apart on selection logic.
    """
    if st.fairness_tracked:
        def sort_key(c):
            share = fairness_state.total_assigned * ctx.weights.get(c.id, 0) / fairness_state.total_weight
            return (
                -(share - fairness_state.actuals.get(c.id, 0)),  # biggest deficit first
                fairness_state.last.get(c.id) or date.min,       # longest-since first
                c.name,
            )
        pick = sorted(cands, key=sort_key)[0]
        share = fairness_state.total_assigned * ctx.weights.get(pick.id, 0) / fairness_state.total_weight
        reason = f"fair share {share:.1f}, done {fairness_state.actuals.get(pick.id, 0)}"
    else:
        pick = min(cands, key=lambda c: (
            (fairness_state.last.get(c.id) or date.min), c.name))
        reason = "rotation"
    return pick, reason


def _seed_fairness_state(st, start, total_weight):
    actuals = fairness.counts(st, start - timedelta(days=WINDOW_DAYS),
                              start - timedelta(days=1))
    total_assigned = sum(actuals.values())
    last = fairness.last_done(st, start)
    return _FairnessState(actuals, last, total_assigned, total_weight)


def run(ctx, actor, result):
    """Ported v1 CoverageRule loop (PER_SLOT semantics) plus PER_WEEK /
    PER_MONTH quota rules, reading availability/cells/counters from ctx
    instead of issuing a query per candidate per slot. Writes go through
    entries.assign(_full_day), then ctx.record(...) keeps the prefetched
    state in sync for the rest of the run.
    """
    total_weight = sum(ctx.weights.values()) or 1
    open_day_set = set(ctx.open_days)

    for rule in CoverageRule.objects.select_related("session_type").order_by(
        "priority", "id"
    ):
        if rule.frequency == CoverageRule.Frequency.PER_SLOT:
            _run_slot_rule(ctx, actor, result, rule, total_weight)
        else:
            _run_quota_rule(ctx, actor, result, rule, total_weight, open_day_set)


def _run_slot_rule(ctx, actor, result, rule, total_weight):
    st = rule.session_type
    state = _seed_fairness_state(st, ctx.start, total_weight)
    full_day = rule.unit == CoverageRule.Unit.PER_DAY

    for day in ctx.open_days:
        if not rule.applies_on(day):
            continue
        slots = [None] if full_day else rule.parts_for()
        for part in slots:
            parts = ["AM", "PM"] if full_day else [part]
            have = min(ctx.count_type(st.id, day, p) for p in parts)
            for _ in range(max(rule.count - have, 0)):
                cands = [c for c in ctx.clinicians
                         if _eligible(ctx, c.id, day, parts, st)]
                if not cands:
                    result.unfilled.append(UnfilledSlot(
                        day, part, st.name, "no eligible clinician"))
                    continue
                pick, reason = _pick(ctx, cands, st, state)
                n = len(parts)
                if full_day:
                    am, pm = entries.assign_full_day(
                        actor, pick, day, st,
                        manually_set=False, fill_reason=reason)
                    ctx.record(am)
                    ctx.record(pm)
                else:
                    e = entries.assign(actor, pick, day, parts[0], st,
                                       manually_set=False, fill_reason=reason)
                    ctx.record(e)
                result.created += n
                state.record(pick.id, day, n)


def _boundary_existing_counts(ctx, st, weeks):
    """One range query per quota rule, at pass start: counts of this
    session type on days that fall inside the week-aligned span but
    outside ctx's own prefetch window [ctx.start, ctx.end] (i.e. a partial
    first/last week). Days inside the window are read from ctx counters
    instead, which also pick up placements made earlier in this pass.
    """
    first_monday = weeks[0]
    last_sunday = weeks[-1] + timedelta(days=6)
    qs = RotaEntry.objects.filter(
        session_type=st, day__range=(first_monday, last_sunday)
    ).exclude(day__range=(ctx.start, ctx.end))
    counts = {}
    for row in qs.values("day"):
        counts[row["day"]] = counts.get(row["day"], 0) + 1
    return counts


def _quota_day_order(rule, ctx, week_days, open_day_set):
    """preferred_weekday_list() first (in that order), then the remaining
    allowed weekdays chronologically; restricted to open days within
    [ctx.start, ctx.end] that the rule applies to."""
    valid = [d for d in week_days
             if ctx.start <= d <= ctx.end
             and d in open_day_set
             and rule.applies_on(d)]
    seen = set()
    order = []
    for wd in rule.preferred_weekday_list():
        for d in valid:
            if d.weekday() == wd and d not in seen:
                order.append(d)
                seen.add(d)
    for d in valid:
        if d not in seen:
            order.append(d)
            seen.add(d)
    return order


def _try_full_day(ctx, actor, result, st, state, day):
    parts = ["AM", "PM"]
    cands = [c for c in ctx.clinicians if _eligible(ctx, c.id, day, parts, st)]
    if not cands:
        return False
    pick, reason = _pick(ctx, cands, st, state)
    am, pm = entries.assign_full_day(
        actor, pick, day, st, manually_set=False, fill_reason=reason)
    ctx.record(am)
    ctx.record(pm)
    result.created += 2
    state.record(pick.id, day, 2)
    return True


def _try_single(ctx, actor, result, st, state, day, part):
    cands = [c for c in ctx.clinicians if _eligible(ctx, c.id, day, [part], st)]
    if not cands:
        return False
    pick, reason = _pick(ctx, cands, st, state)
    e = entries.assign(actor, pick, day, part, st,
                       manually_set=False, fill_reason=reason)
    ctx.record(e)
    result.created += 1
    state.record(pick.id, day, 1)
    return True


def _run_quota_rule(ctx, actor, result, rule, total_weight, open_day_set):
    st = rule.session_type
    rate = accrual.weekly_rate(rule)
    anchor = accrual.epoch_for(ctx.start)
    weeks = ctx.weeks()
    if not weeks:
        return

    boundary_counts = _boundary_existing_counts(ctx, st, weeks)
    state = _seed_fairness_state(st, ctx.start, total_weight)

    for wm in weeks:
        prev_wm = wm - timedelta(days=7)
        week_due = (accrual.due_through(rate, anchor, wm)
                    - accrual.due_through(rate, anchor, prev_wm))
        week_days = [wm + timedelta(days=i) for i in range(7)]
        existing = sum(
            (ctx.count_type(st.id, d, "AM") + ctx.count_type(st.id, d, "PM"))
            if ctx.start <= d <= ctx.end else boundary_counts.get(d, 0)
            for d in week_days
        )
        need = max(week_due - existing, 0)
        if need == 0:
            continue

        candidate_days = _quota_day_order(rule, ctx, week_days, open_day_set)

        for day in candidate_days:
            if need <= 0:
                break
            if (rule.unit in (CoverageRule.Unit.PER_DAY,
                              CoverageRule.Unit.FULL_DAY_PREFERRED)
                    and need >= 2
                    and _try_full_day(ctx, actor, result, st, state, day)):
                need -= 2
                continue
            if rule.unit != CoverageRule.Unit.PER_DAY:
                # 'parts' restricts PER_SESSION only; full-day-preferred's
                # single-session fallback tries both parts, AM before PM.
                allowed_parts = (
                    ("AM", "PM") if rule.unit == CoverageRule.Unit.FULL_DAY_PREFERRED
                    else tuple(rule.parts_for())
                )
                for part in ("AM", "PM"):
                    if need <= 0:
                        break
                    if (part in allowed_parts
                            and _try_single(ctx, actor, result, st, state, day, part)):
                        need -= 1

        for _ in range(need):
            result.unfilled.append(UnfilledSlot(
                wm, None, st.name, "quota unfilled this week"))
