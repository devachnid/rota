"""Personal requirements: each named clinician does a session type once
every N weeks, on no fixed day.

Runs straight after coverage rules, so Duty and standing cover take
first pick of people, and before mentoring, SDL and default fill. For
each week in the run, each clinician who is due gets one session in that
week's cheapest free candidate — the session where the most other people
are available, as SDL chooses. A placement moves the clinician's "last
done" forward. No candidate means "no free session" for that week and
another try next week: due stays due.
"""

from datetime import timedelta

from rota.services import entries, personal

from .scoring import impact_score
from .types import UnfilledSlot, site_for

FILL_REASON = "personal requirement"


def run(ctx, actor, result):
    # Live anywhere in the window; applies_on() gates each day inside it.
    for req in personal.live_requirements(ctx.start, ctx.end):
        st = req.session_type
        people = list(req.clinicians.all())
        if not people:
            continue
        last = personal.last_done(req, [c.id for c in people], ctx.start)
        for c in people:
            in_window = sorted(ctx.days_with_type(c.id, st.id))
            for wm in ctx.weeks():
                week_end = wm + timedelta(days=6)
                seen = [d for d in in_window
                        if d <= week_end and (last[c.id] is None or d > last[c.id])]
                if seen:
                    last[c.id] = max(seen)
                if wm < personal.due_monday(req, last[c.id]):
                    continue
                placed = _place(ctx, actor, result, req, c, wm)
                if placed is None:
                    result.unfilled.append(
                        UnfilledSlot(wm, None, st.name, "no free session"))
                else:
                    last[c.id] = placed


def _place(ctx, actor, result, req, clinician, wm):
    """One session for `clinician` in the week of `wm`, or None."""
    st = req.session_type
    candidates = []
    for i in range(7):
        day = wm + timedelta(days=i)
        if not (ctx.start <= day <= ctx.end and day in ctx.open_day_set
                and req.applies_on(day)):
            continue
        for part in req.parts_for():
            if (ctx.available(clinician.id, day, part)
                    and ctx.is_free(clinician.id, day, part)
                    and clinician.id in ctx.eligible_ids(st)
                    and not ctx.blocked(clinician.id, day, st)):
                candidates.append((day, part))
    if not candidates:
        return None
    candidates.sort(key=lambda dp: (-impact_score(ctx, dp[0], dp[1]), dp[0], dp[1]))
    day, part = candidates[0]
    entry = entries.assign(actor, clinician, day, part, st, site=site_for(st),
                           manually_set=False, fill_reason=FILL_REASON)
    ctx.record(entry)
    result.created += 1
    return day
