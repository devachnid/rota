# Post-merge backlog

Carried from the v1 review process (2026-07-19), plus follow-ups from the
autofill v2 review process (2026-08-22). None are merge-blocking; ordered
roughly by expected value within each section.

Two sweeps on 2026-08-23 cleared the nine user-visible defects (stuck swap
proposals, backwards leave ranges, the unreadable unfilled list, false "behind
target" readings, lost note/site on the eligibility warning, the stage-rule
crash, orphaned locum re-booking, dead leave/swap links) and the six correctness
edges (fairness seeding blind to in-range entries, half-covered full-day
double-cover, the 29 Feb leave-year crash, whole-range trainee accrual seeding,
non-monotonic rotation tie-break, inactive clinicians in eligibility pools).

What remains is internal tidies, a handful of test-coverage gaps, and a section
of decisions that are not defects.

## Behaviour / robustness

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

- Coverage quota rules (`rota/services/fill/coverage.py`): untested — need
  exceeding preferred-day capacity spilling over to non-preferred days
  (the semantic exists and is correct, but no regression test pins it).
  `_boundary_existing_counts` issues its range query even when the fill
  window is already week-aligned (harmless extra query). (The
  non-chronological `last[cid]` rotation skew is fixed: the tie-break value
  is now monotonic.)
- Trainee accrual: only VTS has a regression test for the per-week seeding
  fix; SDL and mentoring share the same helper and call pattern but aren't
  pinned, so a future divergence between the three passes wouldn't be
  caught. Also untested: a session type restricted solely to a
  since-deactivated clinician (should end up restricted to nobody, not
  silently open to everyone).
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
- `tests/test_mentoring.py::test_mentoring_backlog_reports_each_shortfall`
  uses `wte_percent=300` as a lever to force a multi-session week. It's
  honest and commented, but raising the stage rule's `mentoring_per_week`
  would keep domain-nonsense out of the fixture.
