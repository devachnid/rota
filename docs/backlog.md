# Post-merge backlog

Carried from the v1 review process (2026-07-19), plus follow-ups from the
autofill v2 review process (2026-08-22). None are merge-blocking; ordered
roughly by expected value within each section.

The nine user-visible defects that were here — stuck swap proposals, backwards
leave ranges, the unreadable unfilled list, false "behind target" readings,
lost note/site on the eligibility warning, the stage-rule crash, orphaned locum
re-booking, and the dead leave/swap links — were fixed on 2026-08-23. What
remains is correctness edges, internal tidies, and a section of decisions that
are not defects.

## Behaviour / robustness

- Fill fairness seeding: the 91-day window ends the day before the fill range,
  so published/manual duty *inside* the range isn't credited in deficits (mild
  skew, self-corrects next window).
- Fill: a half-covered full-day slot (e.g. manual AM-only duty) gets a full-day
  top-up, briefly double-covering one part; duplicate UnfilledSlot rows appear
  when count-have > 1 with no candidates.
- Leave-year start of Feb 29 raises in non-leap years — validate on
  PracticeSettings.
- `entries.assign` full-replace semantics reset site/note/fill_reason unless
  re-passed — worth a docstring warning. (The two call sites that suffered
  from this — the cell-form warning re-render and full-day assign — are both
  fixed; the sharp edge in the service itself remains undocumented.)
- `part` values aren't validated in edit endpoints (admin-only surface).
- locum_save reaches its 400 on malformed day via an accidental double-parse —
  parse once before the try.

## Structure / style

- Grid view's `works()` closure (`rota/views/grid.py`) still duplicates the
  latest-effective-row-wins pattern logic byte-for-byte — `FillContext.works_on()`
  (`rota/services/fill/context.py`, added in autofill v2) is now the canonical
  batched implementation of the same rule; extract it into a shared service
  and have both the grid and the fill engine call it.
- Magic string "ABSENCE" in reports vs SessionType.Category enum; SessionType
  lacks Meta.ordering (unordered dropdown in locum form).
- my_schedule: missing select_related on two small querysets; "next 28 days"
  range is inclusive (29 days).
- PatternSlot.weekday unbounded (no 0–6 validator); PracticeSettings admin
  allows adding extra rows despite the pk=1 singleton convention.
- Inbox recomputes sessions_affected twice per pending leave request.
- Fairness: inactive clinicians' in-range entries inflate total_assigned while
  being dropped from output — document or exclude.

## Decided — not defects, do not re-raise

These were carried as backlog items but are deliberate choices, recorded here
so they stop being re-reported by each review pass.

- **systemd units run as root.** Correct for this single-purpose LXC. Revisit
  only if the container ever hosts anything else.
- **Axes lockout is keyed on username only.** Correct behind the Cloudflare
  tunnel, where every request carries the tunnel's IP and IP-keying would be
  useless. Accepted consequence: someone who knows a GP's email can lock that
  account for an hour.
- **Fill re-run has no preview step**, though the spec asks for previews on
  destructive actions. Accepted: re-run provably touches only its own unpublished
  drafts, never published or manually-set entries, and that is enforced by tests.
- **Swap audit log records one clinician's name per touched slot** (the other
  appears in the free-text detail). A second row per swap would be a tidier
  trail, but the information is not lost.

## Autofill v2 follow-ups

Found during the v2 review process; none blocked merge.

- `FillContext.eligible_ids()` (`rota/services/fill/context.py`) can return
  inactive clinician ids for restricted session types: the individually
  M2M'd `allowed_clinicians` aren't filtered to `active=True` (only the
  group-membership half is, via `self.clinicians`). Every current caller
  already intersects against active clinicians before use, so it's latent —
  add a docstring note or filter at build time.
- Coverage quota rules (`rota/services/fill/coverage.py`): `last[cid]`
  rotation bookkeeping can go non-chronological within a week because the
  preferred weekday is evaluated before earlier days in the week — bounded
  skew, affects the rotation tie-break only. Also untested: need exceeding
  preferred-day capacity spilling over to non-preferred days (semantic
  exists, no regression test pins it). `_boundary_existing_counts` issues
  its range query even when the fill window is already week-aligned
  (harmless extra query).
- `site=<type>.default_site` is inlined at every placement call site across
  `coverage.py`, `trainees.py`, and `mentoring.py` (six-plus occurrences) —
  worth extracting a small helper now that commitments (which prefer
  `commitment.site`) also thread the same precedence.
- `rota/services/fill/trainees.py`: consider whether the trainee report's
  "expected" column should show the deanery's full entitlement since
  `placement_start` alongside the system-tracked figure from
  `requirements_tracked_from` — currently only the tracked figure is shown,
  which is right for scheduling but understates the placement's total
  contractual requirement.
- `rota/views/reports.py`: `report_trainees` monkeypatches
  `profile.stage_rule` with a lambda to cache the prefetched stage rules —
  works, but a plain helper computing rates from the prefetched dict would
  be less fragile. (The related crash — a deleted `TraineeStageRule` row
  500ing the report and every fill — is fixed: `stage_rule()` now returns
  `None`, `weekly_rates()` yields zero rates, and the admin refuses to
  delete the seeded rows.)
- `rota/services/fill/trainees.py`: `run_vts`/`run_sdl` share most of their
  skeleton (profile loop, accrual due-through, day/part iteration) by copy
  rather than a shared helper; `run_sdl` also unpacks unused `_weekday`/
  `_part` from `weekly_rates()["sdl"]`.
- `rota/services/fill/mentoring.py`: `substitutes` excludes `fixed_trainer`
  by id even though the branch that builds `substitutes` only runs when the
  fixed-trainer branch already found no candidates for the week — harmless
  but redundant.
- `rota/services/swaps.py`: `validate()` walks `involved_slots(req)` twice
  (once with `.exists()`, once with `.first()`) — could merge into one pass
  with a single query per slot.
- Trainee accrual seeds `done` across the whole fill range rather than
  bucketing it by week, so an existing entry sitting in a *later* week of
  the range suppresses one placement in an earlier week (a hand-booked
  week-4 VTS in a 4-week fill yields 3 sessions, not 4). The error
  direction is safe — under-delivery, never a double-booking or a false
  unfilled — and it self-corrects on the next run once those weeks fall
  behind the fill start. Fix by adding existing entries to `done` as the
  week loop advances instead of seeding the whole window up front.
- `tests/test_mentoring.py::test_mentoring_backlog_reports_each_shortfall`
  uses `wte_percent=300` as a lever to force a multi-session week. It's
  honest and commented, but raising the stage rule's `mentoring_per_week`
  would keep domain-nonsense out of the fixture.
