# Personal requirements — design

**Date:** 2026-09-15
**Status:** approved in conversation; spec for review
**Branch:** `feature/personal-requirements` (after `feature/grid-fill-round-2`)

A new kind of rule: *each of these named clinicians does this session type
once every N weeks*. The example is a nursing home ward round — a handful
of GPs each owe one every six weeks, on no fixed day, as an aim to fit in
rather than a fixture. Nothing existing expresses it: a coverage rule
counts practice-wide, so one keen GP could satisfy six people's rounds; a
recurring commitment names a person and an interval but pins a weekday and
silently drops a missed occurrence; the trainee requirement pass is the
right shape but is hard-wired to trainee profiles and stage rules.

## Decisions made in conversation

1. **A new model and a new fill pass**, not a flag on coverage rules and
   not a "flexible" recurring commitment.
2. **Due is rolling from the last one done.** A clinician is due N weeks
   after their most recent session of the type, however it got there. A
   slip restarts the clock from when it actually happened; the aim is
   "never more than N weeks apart", not a fixed calendar cadence.
3. **The pass runs straight after coverage rules**, so Duty and standing
   cover take first pick of people, and before mentoring, SDL and default
   fill.
4. **Shortfalls show on the staffing report and the dashboard**, not in
   the grid's day headers: a rolling aim has no per-day gap.

## Global constraints (unchanged from the project)

- No new dependencies. One migration, `0031`, after the round-2 pair.
- Every placement goes through `rota.services.entries.assign` with
  `manually_set=False` and its own `fill_reason`, so re-runs and Delete
  drafts treat it like every other pass.
- Availability never fails open: a placement needs `ctx.available` and
  `ctx.is_free`, exactly as SDL does.
- A new pass carries the same no-N+1 test as the commitments pass.
- No pre-existing test assertion is weakened.

---

## 1. The model

`PersonalRequirement`, in `rota/models/commitments.py` beside
`RecurringCommitment`, registered in `rota/models/__init__.py`.

| Field | Type | Meaning |
|---|---|---|
| `session_type` | FK `SessionType`, PROTECT, `related_name="personal_requirements"` | what is owed |
| `clinicians` | M2M `Clinician`, `related_name="personal_requirements"` | who owes it |
| `interval_weeks` | `PositiveSmallIntegerField`, default 6 | one every this many weeks |
| `part` | `AM` / `PM` / `EITHER`, default `EITHER` | which half-day it may take |
| `weekdays` | `CharField`, blank | int list, Monday = 0; blank = every open day |
| `active_from` | `DateField` | the clock starts here for anyone with none yet |
| `active_until` | `DateField`, null | inclusive; blank = open-ended |

- `Meta.ordering = ["session_type__name", "interval_weeks", "id"]`.
- `__str__`: "Nursing home round every 6 weeks".
- `clean()`: `interval_weeks >= 1`; `weekdays` through
  `ranges.validate_int_list` with the weekday span, as `CoverageRule`
  does; `active_until` not before `active_from`.
- `weekday_list()` and `applies_on(day)` mirror `CoverageRule`'s, blank
  meaning every open day. `parts_for()` returns `["AM"]`, `["PM"]` or
  `["AM", "PM"]`.
- `rota/checks.py`'s `rota.E006` loop adds this model's `weekdays`, so a
  stored value that no longer parses stops at deploy like the others.

### Admin

- `PersonalRequirementAdmin` under Sessions & rules in the sidebar, after
  Coverage rules: `list_display` of session type, "every N weeks", part,
  weekdays, active from/until and a clinician count; `filter_horizontal`
  on `clinicians`; `list_filter` on session type.
- `PersonalRequirementForm` in `rota/admin_forms.py`: `weekdays` through
  `IntListCheckboxField` as the coverage rule form does; `clinicians`
  limited to active clinicians; `clean()` rejects any chosen clinician
  who is not eligible for the session type (`SessionType.is_eligible`),
  naming them. The M2M is validated on the form because the model cannot
  see it before save.

---

## 2. When one is due

`rota/services/personal.py`, the single reader of "last done" and "due"
so the fill, the report and the dashboard cannot disagree.

- `last_done(requirement, clinician_ids, before, *, include_drafts) ->
  {clinician_id: date | None}`: one query, `Max("day")` per clinician over
  `RotaEntry` rows of the session type on `day < before`. Drafts count for
  admins: a planned round is still a round. Non-admin readers pass
  `include_drafts=False`, matching the reports' existing rule.
- `due_monday(requirement, last)`: `week_monday(last) + interval_weeks *
  7` when `last` is a date, else `week_monday(active_from)`.
- `status(requirement, clinician, today, *, include_drafts) ->
  Status(last, due, weeks_overdue)`: `weeks_overdue` is
  `(week_monday(today) - due) // 7` floored at zero. Three readings fall
  out of it: on track (due after this week), due this week, overdue by n
  weeks.
- A requirement is **live** on a day when `active_from <= day` and
  `active_until` is blank or `>= day`. Outside that nothing is due and
  nothing is placed.

---

## 3. The fill pass

`rota/services/fill/personal.py`, `run(ctx, actor, result)`, wired into
`run_fill` in `rota/services/fill/__init__.py` immediately after
`coverage.run`.

- **Seed.** For each requirement live anywhere in `ctx.start..ctx.end`,
  with its clinicians prefetched: `last = last_done(req, ids, ctx.start,
  include_drafts=True)`. `FillContext` gains `days_with_type(clinician_id,
  session_type_id) -> set[date]`, built from the entries it already
  prefetches, so in-window sessions of the type placed by hand or by an
  earlier pass are folded in as the weeks are walked.
- **Walk.** For each week Monday `wm` in `ctx.weeks()`, for each clinician
  of each requirement, in `display_order, name` order:
  1. Fold in any in-window session of the type on or before this week's
     last day: `last = max(last, those days)`.
  2. If `wm < due_monday(req, last)`, skip: not due yet.
  3. Otherwise collect candidates: each day of the week that is inside
     `ctx.start..ctx.end`, open, in the requirement's live window and
     weekdays; each part in `parts_for()`; where `ctx.available`,
     `ctx.is_free`, the clinician is in `ctx.eligible_ids(st)` and not
     `ctx.blocked(cid, day, st)`. Sort by `(-impact_score(ctx, day,
     part), day, part)` — the session where the most other people are
     available, as SDL does — and place the first through
     `entries.assign(..., manually_set=False, fill_reason="personal
     requirement")`, `site=site_for(st)`, `ctx.record(entry)`,
     `result.created += 1`, `last = day`.
  4. If there is no candidate, `result.unfilled.append(UnfilledSlot(wm,
     None, st.name, "no free session"))` and leave `last` alone, so the
     clinician is still due next week.
- One placement per clinician per week, and nothing is placed before it
  is due: the aim is an interval, not a quota to get ahead on.
- **Queries.** One per requirement for the seed, plus the prefetch;
  nothing per week or per clinician. A `CaptureQueriesContext` test in the
  shape of `test_commitments_pass_has_no_n_plus_one` pins it.

---

## 4. Visibility

### Staffing report

- `report_staffing` gains `personal_rows` from `personal.status()` over
  every live requirement and its clinicians, `include_drafts` following
  the existing admin rule. The template renders a "Personal requirements"
  table after the accrual table: requirement ("Nursing home round, every
  6 weeks"), clinician, last done ("Mon 4 Aug" or "never"), due ("week of
  15 Sep"), status ("on track", "due this week", "2 weeks overdue" in
  the `warn` class). Rows sorted overdue first, then due, then on track,
  then by clinician. The section is omitted when there are no live
  requirements.

### Dashboard

- `admin_dashboard.health()` gains "Clinicians overdue a personal
  requirement": the count of (requirement, clinician) pairs with
  `weeks_overdue > 0` today, linking to the staffing report. Level
  `warn`.

### Fill result

- "no free session" already exists as an SDL reason; the unfilled list
  groups by session type and reason, so the ward round's rows are their
  own line. The reasons table in `docs/admin/day-to-day.md` says the
  reason now also covers personal requirements.

---

## 5. Documentation

- `docs/admin/coverage-rules.md`: a "Personal requirements" section after
  Coverage rules — what it is for, each field, the rolling clock with a
  worked example (six GPs, six weeks, one slips a fortnight), and what it
  is not (not a fixture: use a recurring commitment; not a practice-wide
  quota: use a per-month coverage rule).
- `docs/admin/day-to-day.md`: the pass list becomes seven, the new pass
  fourth; the reasons table row.
- `README.md`'s spec list; `docs/backlog.md` Settled entry.

## Tests

- Model: `clean()` on interval, weekdays and the date window; `__str__`;
  `applies_on` blank-means-every-day; the form's eligibility rejection;
  `rota.E006` on a bad stored weekday list.
- Service: `last_done` per clinician with and without drafts;
  `due_monday` from a date and from `active_from`; `status` on track /
  due / overdue arithmetic across a year boundary.
- Fill: a clinician with none yet is placed in the first live week; one
  done three weeks ago on a six-week interval is not placed; one done
  seven weeks ago is placed in the first week of the run; a hand-placed
  session of the type inside the window resets the clock; no free session
  reports and the clinician is placed the following week; `part` and
  `weekdays` restrict candidates; the cheapest session wins; a session
  type `blocks_same_day` is honoured; the pass runs after coverage (Duty
  wins a contested session); the no-N+1 query test.
- Report and dashboard: rows and count from a fixture with one overdue,
  one due, one on track; non-admin excludes drafts.

## Not done, on purpose

- A full-day requirement, preferred weekdays, or a site override — none
  needed for the ward round; add when a real one asks.
- Membership by group rather than named clinicians.
- Placing early to smooth the calendar. Due means due.
- A grid marker for "due this week". The report is the place to look.
