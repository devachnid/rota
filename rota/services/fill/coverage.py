from datetime import date, timedelta

from rota.models import CoverageRule
from rota.services import entries, fairness

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


def run(ctx, actor, result):
    """Ported v1 CoverageRule loop (PER_SLOT semantics), reading
    availability/cells/counters from ctx instead of issuing a query per
    candidate per slot. Writes go through entries.assign(_full_day), then
    ctx.record(...) keeps the prefetched state in sync for the rest of the
    run.
    """
    start = ctx.start
    total_weight = sum(ctx.weights.values()) or 1

    for rule in CoverageRule.objects.select_related("session_type").order_by(
        "priority", "id"
    ):
        st = rule.session_type
        actuals = fairness.counts(st, start - timedelta(days=WINDOW_DAYS),
                                  start - timedelta(days=1))
        total_assigned = sum(actuals.values())
        last = fairness.last_done(st, start)
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
                    if st.fairness_tracked:
                        def sort_key(c):
                            share = total_assigned * ctx.weights.get(c.id, 0) / total_weight
                            return (
                                -(share - actuals.get(c.id, 0)),  # biggest deficit first
                                last.get(c.id) or date.min,       # longest-since first
                                c.name,
                            )
                        pick = sorted(cands, key=sort_key)[0]
                        share = total_assigned * ctx.weights.get(pick.id, 0) / total_weight
                        reason = f"fair share {share:.1f}, done {actuals.get(pick.id, 0)}"
                    else:
                        pick = min(cands, key=lambda c: (
                            (last.get(c.id) or date.min), c.name))
                        reason = "rotation"
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
                    actuals[pick.id] = actuals.get(pick.id, 0) + n
                    total_assigned += n
                    last[pick.id] = day
