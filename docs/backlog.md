# Post-merge backlog

Carried from the v1 review process (2026-07-19), plus follow-ups from the
autofill v2 review process (2026-08-22). None are merge-blocking; ordered
roughly by expected value within each section.

## Behaviour / robustness

- Fill fairness seeding: the 91-day window ends the day before the fill range,
  so published/manual duty *inside* the range isn't credited in deficits (mild
  skew, self-corrects next window).
- Fill: a half-covered full-day slot (e.g. manual AM-only duty) gets a full-day
  top-up, briefly double-covering one part; duplicate UnfilledSlot rows appear
  when count-have > 1 with no candidates.
- Fill re-run has no preview step (spec asks for previews on destructive
  actions); accepted because re-run provably only touches its own drafts.
- Swap audit log records only the proposer's name per touched slot; two rows
  (one per clinician) would be a cleaner trail.
- Orphaned-then-recovered locum requirement: re-booking requires stepping back
  to ADVERTISED first (direct re-BOOK no-ops the clinician).
- Leave-year start of Feb 29 raises in non-leap years — validate on
  PracticeSettings.
- `entries.assign` full-replace semantics reset site/note/fill_reason unless
  re-passed — document in a docstring; the cell-form warning re-render drops
  typed note/site; full-day assign discards site/note.
- `part` values aren't validated in edit endpoints (admin-only surface).
- Swap proposals can target clinicians with no linked user (stalls at
  PROPOSED); filter `user__isnull=False` in swap_new.
- `leave_new` accepts end_date < start_date (approves as a no-op).
- Grid nav shows Request leave / Propose swap to admin accounts with no
  clinician profile (403 on click).
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
- systemd units run as root (fine for this LXC; note if hardening later).
- Axes lockout is username-only (correct behind the tunnel, but means a known
  email can be locked for 1h by anyone) — noted here as a documented tradeoff.

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
- `rota/services/fill/commitments.py`: local variable `commitments` shadows
  the module's own name — rename to `qs` for readability.
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
