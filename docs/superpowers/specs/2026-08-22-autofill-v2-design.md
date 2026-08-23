# Autofill v2 — Design

**Date:** 2026-08-22
**Status:** Approved design, pre-implementation
**Builds on:** v1 spec (`2026-07-18-gp-rota-design.md`) and the shipped v1 engine.

## Purpose

Close the gap between the app's assisted fill and the real manual rota process.
V1 fills duty and simple coverage rules; the manual process also places trainee
education sessions, paired mentoring, demand-driven specialist clinics, branch-site
(PMC) cover, and per-clinician fixed weekly commitments. Autofill v2 makes all of
those data-configured and auto-placed, keeping v1's philosophy: a transparent,
priority-ordered greedy engine whose every placement carries its reasoning —
not a constraint solver.

All observed rules below were verified against the practice's real "Rota 2026"
spreadsheet and confirmed by the rota owner.

## Domain rules being encoded

### Trainees

- Trainees (FY2 / ST1 / ST2 / ST3) have a WTE percentage (100/80/60/50 typical)
  and a placement date range.
- Weekly educational entitlement, scaled by WTE:
  - **ST2/ST3 (and ST1, seeded the same as ST2):** 1 VTS + 1 SDL + 1 mentoring.
  - **FY2:** 2 SDL + 1 mentoring, no VTS.
- VTS is anchored: **ST3 = Tuesday PM, ST2 = Tuesday AM** (stage-configurable).
- SDL floats to any session, preferring sessions where Routine cover is
  thickest (least appointment impact).
- LTFT scaling is pro-rata by WTE: e.g. 60% → 0.6 mentoring/week, realized as
  alternating weeks that average out over the month (matches the deanery
  pro-rata table).
- **Mentoring is a pair:** trainee + their fixed named trainer occupy the same
  session, both marked Mentoring. If the fixed trainer is on leave that week, a
  substitute is drawn from the trainer pool. There may be more trainers than
  trainees. Placement uses the same thickest-Routine preference as SDL.

### Demand-driven clinics

- **Vas Clinic:** at least 2 sessions/week (configurable; volume rising).
  Preferred day Thursday, then Tuesday. Full day with one clinician preferred;
  split into separate sessions allowed. Skill pool configured as data; shared
  evenly within the pool.
- **Coil Clinic:** average 2 sessions/month. Pool + even sharing.
- **Minor Ops:** average 1 session/month. Pool + even sharing.
- **Baby Clinic:** every Tuesday PM, one clinician from its pool (expressible
  in v1 already; listed for completeness).

### PMC (Penrhiwceiber Medical Centre — branch site)

- Two doctors cover PMC each open day:
  - One **PMC-Urgent** all day, every day, year-round.
  - One **PMC-Routine**: **winter (Oct–Apr)** all day; **summer (May–Sep)** AM
    only, with a non-duty session in their PM.
- Pool: partners and salaried GPs only (no trainees, no PA) — group-based
  eligibility.
- No fairness counting: simple rotation (longest-since-last).
- PMC session types carry the branch site automatically.

### Fixed personal commitments

Recurring per-clinician fixtures (e.g. Vision Mon AM + Wed AM for one GP;
Proactive all-day Monday for another; Occ Health Thursdays) — fully
admin-configured data, never code. Support an every-N-weeks interval
(default weekly).

## Data model

### New models

- **TraineeProfile** — OneToOne on Clinician: `stage`
  (FY2/ST1/ST2/ST3 choices), `wte_percent` (positive integer, e.g. 100/80/60/50),
  `trainer` (FK Clinician, nullable), `placement_start`, `placement_end`.
  Requirements are generated only inside the placement window.
- **TraineeStageRule** — one row per stage, admin-editable, seeded by data
  migration: `stage` (unique), `vts_per_week`, `sdl_per_week`,
  `mentoring_per_week` (decimals), `vts_weekday` (nullable), `vts_part`
  (nullable). Seeds: ST3 = 1/1/1 + Tue PM; ST2 = 1/1/1 + Tue AM; ST1 = as ST2;
  FY2 = 0 VTS / 2 SDL / 1 mentoring.
- **RecurringCommitment** — `clinician`, `session_type`, `weekday`, `part`
  (AM/PM/BOTH), `site` (nullable), `active_from`, `active_until` (nullable),
  `interval_weeks` (default 1, anchored to the ISO week of `active_from` — a
  fortnightly fixture fires in weeks an even number of weeks after it). BOTH
  stamps AM and PM.

### Extended models

- **Clinician**: `is_trainer` boolean (mentor pool; substitution source).
- **SessionType**: `default_site` (FK, nullable — PMC types stamp the branch
  site on placement), `blocks_same_day` (M2M to SessionType, blank = none):
  a clinician holding this type on a day is excluded from being auto-assigned
  any of the listed types that day. Configured: PMC-Routine blocks {Duty} —
  exactly the "non-duty PM" rule, without hardcoding what "duty" means.
- **CoverageRule**:
  - `months` — CSV of month numbers like the existing `weekdays` CSV; empty =
    all year. `applies_on(day)` checks both.
  - `frequency` — `PER_SLOT` (default; exactly today's semantics: `count` per
    applicable slot), `PER_WEEK` (`count` sessions per ISO week), `PER_MONTH`
    (`count` sessions per month on average, placed by weekly-rate accrual).
  - `preferred_weekdays` — ordered CSV consulted when the rule has placement
    freedom (PER_WEEK/PER_MONTH); empty = chronological.
  - `unit` gains `FULL_DAY_PREFERRED` — try one clinician across AM+PM of the
    same day; fall back to independent per-session placements.
- **PracticeSettings**: `vts_session_type`, `sdl_session_type`,
  `mentoring_session_type` (FKs, nullable — the trainee engine is wired by
  configuration, not hardcoded names; passes no-op when unset).
- **RotaEntry**: `companion_group` — nullable UUID shared by the two halves of
  a mentoring pair, mirroring the proven `allocation_group` mechanism (which
  stays reserved for "one clinician's AM+PM pair" and swap-expansion; reusing
  it would corrupt swap semantics). Clearing either companion entry clears both (service-level,
  logged). Swaps involving a companion-linked entry are rejected with a clear
  message in v2 (swap the mentoring session by re-running fill or manual edit
  instead); revisit if it proves annoying.

### Initial rule data (configured via admin, not migrations)

Duty (unchanged), Baby Clinic Tue PM, Vas PER_WEEK 2 FULL_DAY_PREFERRED
preferred Thu>Tue, Coil PER_MONTH 2, Minor Ops PER_MONTH 1, PMC-Urgent PER_SLOT
PER_DAY all year, PMC-Routine winter PER_SLOT PER_DAY months 10–4, PMC-Routine
summer PER_SLOT PER_SESSION AM months 5–9. Vas/Coil/Minor-Ops session types get
`fairness_tracked=True` (even sharing); PMC types stay untracked (rotation).

## Fill pipeline

`run_fill(actor, start, end, fill_default)` keeps its signature and becomes an
orchestrator over ordered passes. `rota/services/fill.py` becomes the package
`rota/services/fill/`:

```
fill/__init__.py     run_fill orchestrator (delete-own-drafts, pass order, result)
fill/context.py      FillContext: one-shot prefetch of patterns, entries, rules,
                     settings; in-memory cell map updated as passes place entries
                     (removes the v1 per-candidate query pattern)
fill/accrual.py      expected-vs-actual deficit maths (see below)
fill/scoring.py      thickest-Routine impact scorer (shared by SDL + mentoring)
fill/commitments.py  pass 1
fill/trainees.py     pass 2 (VTS) and pass 5 (SDL)
fill/coverage.py     pass 3: all CoverageRules by priority (duty, PMC, vas, …)
fill/mentoring.py    pass 4
```

**Pass order:** commitments → trainee VTS → coverage rules (by `priority`) →
mentoring → SDL → default Routine fill. Rationale: immovable things first,
scarcest constraints next, floating placements after the board is mostly known
(so the impact scorer sees reality), Routine last.

**Re-run safety is unchanged:** the pre-pass delete still removes only
`is_published=False AND manually_set=False` entries in range; every pass writes
drafts via the entries service with a `fill_reason`; published and manual
entries are never touched, and existing coverage is subtracted before placing.

### Accrual (LTFT + weekly/monthly quotas)

Stateless, computed from the DB each run (like fairness):

- Each requirement has a weekly rate: trainee entitlements = stage rule ×
  WTE/100; PER_WEEK rules = `count`; PER_MONTH rules = `count × 12 / 52.18`.
- Anchor: `placement_start` for trainee requirements; for PER_WEEK/PER_MONTH
  coverage rules, the Monday of the ISO week containing Jan 1 of the year of
  the fill range's `start` date (fixed epoch → deterministic re-runs, defined
  even when the range spans New Year).
- **Trainee requirements (cumulative):** deficit = (rate × whole weeks since
  placement start, floored) − (actual entries since placement start). Place
  while deficit ≥ 1. Placement start is a true anchor with real history, so
  this self-corrects around leave and manual over-delivery with no cold-start
  burst.
- **PER_WEEK / PER_MONTH coverage rules (incremental):** each week's quota =
  due-through(this week) − due-through(previous week), minus entries of the
  type already in that week. The epoch supplies only the rounding phase — a
  fresh install mid-year does NOT owe a backlog of sessions accrued since
  January.

### Placement details

- **VTS:** anchored weekday/part from the stage rule; skipped (and reported
  unfilled) if the trainee isn't in that session per pattern or is on leave.
- **Mentoring:** candidate sessions = both trainee and trainer pattern-in,
  cells empty, session open. Trainer = fixed trainer; if on leave for every
  candidate that week, substitutes from `is_trainer` clinicians. A trainer
  mentors at most one trainee per session. Best candidate by impact score.
  Writes both entries companion-linked in one transaction.
- **SDL:** candidate sessions = trainee free; best by impact score.
- **Impact score** of a session = number of active clinicians pattern-available
  there whose cell is still empty at scoring time (they would otherwise be
  Routine). Higher = thicker cover = better place to absorb a non-routine
  session.
- **FULL_DAY_PREFERRED (vas):** iterate `preferred_weekdays` then remaining
  allowed days; try one pool clinician free+eligible both parts (fairness pick);
  fall back to two independent sessions, preferred days first.
- **Same-day blocking:** when placing type T, exclude clinicians who already
  hold (that day) any type whose `blocks_same_day` lists T (summer PMC-Routine
  → no Duty that PM). The existing one-fairness-per-day gate stays.
- **Site stamping:** entries created for a type with `default_site` (or from a
  commitment with a site) carry it.

### Fairness scoping

`fair_shares`/fill deficits for a session type divide among clinicians eligible
for that type (`SessionType.is_eligible`), not all active clinicians. Duty
(unrestricted) is numerically unchanged. Weights remain weekly pattern
sessions.

## Configuration & UI

- **Admin:** TraineeProfile inline on Clinician; TraineeStageRule table;
  RecurringCommitment admin (filter by clinician); new CoverageRule fields;
  PracticeSettings type pickers; `is_trainer` on the Clinician list.
- **Grid:** mentoring cell tooltip names the partner ("Mentoring — with Bethan
  C"); PMC entries show the branch-site marker via `default_site`. No layout
  changes.
- **Reports:**
  - Fairness report gains Vas/Coil/Minor-Ops tables automatically (they become
    fairness-tracked) with pool-scoped shares.
  - New **Trainee requirements report**: per trainee, WTE-adjusted expected vs
    delivered VTS/SDL/Mentoring for the placement to date.
  - Staffing report gains an **accrual section**: PER_WEEK/PER_MONTH rules
    behind target ("Vas: 1 session behind target this month").
- **Fill screen:** unchanged; unfilled list now includes trainee requirement
  and pairing failures with reasons ("mentoring for N. Mayoub: no session with
  trainer free").

## Warnings & edge handling

- Day-level warnings check PER_SLOT rules only; a single day cannot "miss" a
  weekly quota. Weekly/monthly deficits appear in the staffing report accrual
  section and fill results instead.
- Trainee without a trainer: mentoring reported unfilled, never an error.
- Commitments never overwrite leave or manual/published entries and skip
  closed days; leave always wins.
- Soft problems warn, never block (v1 philosophy unchanged).

## Testing

- Accrual unit tests: 100%/60%/50% WTE alternation over 8+ weeks, PER_MONTH
  cadence, self-correction after leave and after manual over-delivery.
- Mentoring: fixed-trainer placement, substitution on leave, one-trainee-per-
  trainer-per-session, no-mutual-session unfilled, companion clear cascades,
  swap-rejection on companion entries.
- Coverage: month windows (winter/summer PMC switch at boundaries),
  FULL_DAY_PREFERRED full-day and split fallbacks with preferred-day order,
  blocks_duty_same_day gate.
- Fairness: pool-scoped denominators; duty unchanged on unrestricted types.
- Pipeline: pass-order integration test on a realistic week; **v1 regression
  test — fill on v1-shaped data (no new config) produces identical output**.
- Migration: all new fields nullable/defaulted; existing rules keep PER_SLOT.

## Out of scope (this sub-project)

- Frontend modernization (separate sub-project B).
- Backlog sweep (separate sub-project C), except the fill prefetch/context
  rework, which lands here because the package split touches the same code.
- Swap-with-companion support (rejected with message; revisit on demand).
- Locum/PA-specific rules beyond existing behavior.
