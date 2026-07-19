# Post-merge backlog

Carried from the v1 review process (2026-07-19). None are merge-blocking; ordered
roughly by expected value.

## Behaviour / robustness

- Fill performance: ~6 queries per candidate check, measured 10,206 queries /
  5.9s worst case (15 clinicians, 4 weeks, default fill). Cost scales linearly
  with range length (~20s for a quarter). If long fills become a thing, add a
  caching pass (batch pattern/entry prefetch) or cap the fill range in the UI.
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

- Grid view's `works()` closure duplicates the availability service's
  latest-effective-row-wins rule — extract a batched service variant.
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
