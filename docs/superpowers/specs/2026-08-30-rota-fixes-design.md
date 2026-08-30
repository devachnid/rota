# Rota fixes and clinician lifecycle — design

**Date:** 2026-08-30
**Status:** Approved design, pre-implementation
**Builds on:** v1 (`2026-07-18-gp-rota-design.md`), autofill v2
(`2026-08-22-autofill-v2-design.md`) and frontend Phase 1
(`2026-08-23-frontend-phase1-design.md`), all merged.

## Purpose

Thirteen items found during the first real use of the deployed app: six bugs
and seven improvements. Three of the bugs share a root cause, two of them
compound each other, and three of the features turn out to be the same
question asked in different places — so this is one body of work rather than
thirteen.

The spine is **availability**: the question "can this clinician be given this
session?" is currently answered in more than one place and knows about only
one input (the working pattern). Clinician start/end dates and approved leave
both belong in that answer. Consolidating them is what makes the rest small.

## What was found

Each of these was reproduced against the code before being designed for; none
is speculative.

### The pattern editor destroys the current pattern (three reported bugs, one cause)

`bulk_set_pattern` and the admin view are **correct**. Posting a future
`effective_from` — with or without existing slots — creates only the changed
rows at that date and leaves earlier rows alone. Verified.

The fault is in `templates/admin/rota/patternslot/bulk_form.html`. The date
input lives in a `method="get"` form; the checkboxes and a **hidden copy** of
`effective_from` live in a separate `method="post"` form. Nothing synchronises
them, so changing the date and pressing Save posts the stale value — normally
today, which is precisely the value that overwrites the live pattern.

This explains all three reports:

- *"Future effective-from overwrites the current pattern"* — it saved at today.
- *"A future date is ignored when the clinician has no slots"* — same.
- *"Load does not show the current pattern"* — a consequence, not a separate
  bug. When two saves both land on today, the second updates the first **in
  place**, so nothing survives before today and the editor correctly displays
  an empty prior pattern. The data is damaged; the display is honest.

Compounding it, the view silently substitutes `date.today()` for an
unparseable date, turning bad input into the most destructive valid value.

### Approving leave can silently do nothing

`leave.approve()` writes entries for `sessions_affected(req)`, which
intersects the requested range with the clinician's **working pattern**. A
clinician with no pattern covering those dates yields zero sessions: the
request flips to APPROVED, the admin gets a success message, and no entry
exists. Reproduced — the same request produced 0 entries without a pattern and
8 with one.

Nothing on the grid, and nothing for the fill engine, which reads entries
rather than requests. On the staging data — where half the clinicians had no
pattern and some had patterns damaged by the bug above — this presented as
"leave does not work".

A second-order version bites later: leave is materialised **once**, against
the pattern as it stood at approval. Enter a pattern afterwards and the leave
does not follow, because nothing re-runs approval.

### Coverage rule month ranges are not parsed

`CoverageRule.applies_on` does `int(x) for x in self.months.split(",")`, so
`1-6,9-12` raises `ValueError`, surfacing to the user mid-fill as
`Bad request: invalid literal for int() with base 10: '1-6'`. The same
unguarded parse serves `weekdays` and `preferred_weekdays`, and there is no
validation, so the failure lands at fill time rather than at save time.

### Clinician deletion is blocked outright

`RotaEntry.clinician` is `PROTECT`, so deletion fails whenever any entry
exists, published or not — and it fails while rendering the **confirmation
page**, before any delete code runs.

## Design

### 1. Availability

`PatternResolver` stays as it is and stays internal: latest-effective-row-wins
is a distinct, separately-testable concern.

A new `AvailabilityResolver` in `rota/services/availability.py` owns a
`PatternResolver` plus the two new inputs, and answers three questions:

| Method | Meaning |
|---|---|
| `works_on(clinician_id, day, part)` | Active, inside the date window, and the pattern says yes |
| `on_leave(clinician_id, day, part)` | An approved `LeaveRequest` spans that day |
| `available(clinician_id, day, part)` | `works_on` and not `on_leave` |

Composition order, cheapest first: `active` → date window → pattern → leave.
All four are read at one moment by one call, so they cannot disagree — which
is the risk in having `active` and the dates be separate concepts.

`LeaveRequest` stores dates, not parts, so leave is whole-day across its range
and `on_leave` ignores `part`.

**Consumers.** The fill engine (`FillContext`) asks `available()`. The grid
asks `works_on()` and `on_leave()`. Both already construct a `PatternResolver`,
so this is one changed constructor call each, plus one prefetch of approved
leave overlapping the window. No new per-cell queries; asserted by a
query-count test rather than by inspection.

**Why leave is read directly** rather than inferred from entries: entries only
exist where the pattern said the clinician works. If a pattern is later
widened, a re-run would schedule over approved leave. Reading the requests
closes that permanently.

### 2. Grid rendering

Cell precedence:

```
entry exists                → render the entry
else on_leave and ghostable → render a ghosted leave chip
else works_on               → grey (--sunken): working, nothing allocated
else                        → page background: not working
```

This inverts the current treatment, as requested: blank means "not here", grey
means "here and unallocated" — the state that needs attention.

A ghosted chip (outlined rather than filled) marks approved leave with no
underlying entry. `ghostable` is true when **either**:

- `works_on` is true — approval should have written an entry here and did not,
  so the ghost is the visible signal that something went wrong; or
- the clinician has **no pattern rows at all** — nothing would ever render for
  them otherwise, which is the case that presented as "leave does not work".

Both clauses are needed, and the qualifier matters. Ghosting every session a
leave request spans would put chips on a part-timer's non-working days every
time they took a week off — noise on exactly the rows that should be quiet.
Ghosting only where `works_on` is true would leave a clinician with no pattern
showing nothing at all, which is the original complaint. Together they are
silent when the data is right and loud precisely where it is wrong.

The `works_on` clause also self-corrects over time: enter a pattern after
approving leave, and the ghosts appear at that moment, because the sessions
become worked while no entry exists.

A session outside a clinician's start/end window renders blank, identical to a
non-working session. No distinct "not yet started / left" treatment.

**Warnings** render only for `is_rota_admin` — and are not computed otherwise.
**Day notes render for everyone**: they are practice information, not staffing
alerts.

### 3. Leave

**Visibility and accounting are deliberately separated.** Conflating them is
what allowed the silent failure — the grid appeared to show the truth when it
was showing a side effect.

- **Entries remain the accounting record.** They drive entitlement. Ghosted
  chips consume no allowance.
- **The resolver drives visibility and scheduling.** Approved leave shows on
  the grid immediately and is never scheduled over, whatever the entries say.

Approval still writes entries only where the clinician works. Writing them for
non-working sessions would inflate leave balances with sessions that were
never going to be worked.

**The consequence moves before the decision.** The requests inbox already
previews overwritten entries; it gains a count of what approval will write:

> Writes **8 sessions** (Mon 7 – Thu 10 Sep)

and, when that is zero, prominently:

> ⚠ Writes **no sessions** — this clinician has no working pattern covering
> 3–7 Sep. Approving records the decision, but the leave will not count
> towards their entitlement.

Approval is **not blocked**. The admin has decided; the interface simply stops
misrepresenting the outcome. A partial count — a part-timer getting 4 of 10 —
is normal and reads as information.

**Out of scope, deliberately:** pending leave remains invisible to the fill
engine. There is an argument it should not be, but that changes what "pending"
means and belongs in its own decision.

### 4. Pattern editor

**One form.** Clinician select, date input and checkboxes all in a single
`method="post"` form, with two submits distinguished by name:

```html
<button name="action" value="load">Load</button>
<button name="action" value="save">Save pattern</button>
```

`load` re-renders at the chosen date without writing; `save` writes. The date
on screen is the date that posts. The bug is not patched — the mechanism that
allowed it is removed. Changing the clinician still auto-submits as a load.

**An unparseable date is refused**, not silently replaced with today. Bad input
must not resolve to the most destructive valid value.

**Pattern history is shown.** A read-only table above the grid lists each
`effective_from` and the sessions it sets. The editor currently shows one
date's worth with no hint that anything else exists, which is what made the
damage invisible.

**A read-only report for the damaged data.** `manage.py pattern_report` prints
each clinician's rows grouped by `effective_from`, flagging two signatures: a
clinician whose entire history sits at a single date, and rows dated today.
It changes nothing and guesses at nothing — the original values were
overwritten in place, so there is nothing to recover, only damage to see and
re-enter through the fixed editor.

### 5. Clinician lifecycle

**Dates.** `start_date` and `end_date` on `Clinician`, both nullable (null =
unbounded), inclusive at both ends. They sit **alongside** `active` rather
than replacing it, and join the resolver's composition, so a session outside
the window is not schedulable anywhere: the engine skips it, the grid renders
it blank, and leave approval writes nothing there and says so.

Validation: `end_date` not before `start_date`. On save, entries already
outside the new window produce an admin message with a count. **Nothing is
deleted** — silently destroying published rota because of a typed date is the
wrong trade.

**Deletion.** Because `PROTECT` fires while rendering the confirmation page,
the guard lives in `get_deleted_objects`, not only `delete_model`:

- Unpublished entries are listed as "will also be deleted", then deleted with
  the clinician in one transaction.
- Any published entry refuses the deletion, naming the count.

The refusal offers a real alternative: a **Deactivate selected clinicians**
admin action, one click away rather than a second trip into the record.

The confirmation page also surfaces what else a successful delete takes with
it, rather than leaving it to Django's default rendering: pattern slots, leave
requests, recurring commitments and the trainee profile all cascade, as do
swap requests — **including ones where this clinician was the colleague**,
which touches another clinician's history. Locum requirements are set null, so
the booking survives without the name. The audit log is unaffected: it stores
clinician names as text rather than a foreign key.

### 6. Smaller items

**Range parsing.** One shared parser accepting `1-6,9-12` as well as `1,2,3`,
used by `months`, `weekdays`, `preferred_weekdays` and `open_weekdays` so they
behave alike. `clean()` validates bounds (months 1–12, weekdays 0–6) so a typo
fails at save with a readable message.

**Colour previews in admin.** The session-type list gains a swatch rendered
from the tint's own background and foreground — no hardcoded colours. The
colour field gains a custom widget: 42 labelled swatches as radio inputs,
because `<option>` background styling is not reliable across browsers and a
grid is a better way to pick from 42 than a long dropdown.

**Light/dark toggle.** A nav control cycling **system → light → dark**,
persisted in `localStorage`. No model change, no new dependency; the
three-state CSS and the `[data-theme]` hooks already exist for exactly this.
Three states rather than two on purpose — a two-way toggle would strand the
`prefers-color-scheme` path. The attribute must be set in `<head>` before first
paint or every load flashes the wrong theme.

**Assisted fill checkbox.** Ticked by default, labelled with the configured
type: "Fill remaining empty cells with **Routine**". When no default type is
configured the box does nothing at all, silently — worse now that it defaults
on — so it is disabled with an explanation pointing at the setting.

## Constraints

- **No new dependencies, no build step.** As with every phase.
- Hand-written CSS with custom properties; the palette remains the only source
  of session colours.
- The existing test suite must pass unmodified except where behaviour
  deliberately changes (grid cell classes, fill checkbox default).
- `DEBUG` defaults off; tests and dev opt in. Any new management command must
  work under the deployed configuration.

## Testing

Every reproduction in "What was found" becomes a permanent test, because each
is a bug that shipped without one:

- Posting a future `effective_from` through the **form** lands rows at that
  date — the form-level test that was missing while the service-level ones
  passed.
- An unparseable date is refused rather than treated as today.
- Approving leave with no covering pattern writes nothing, the preview says
  zero, and the request still records the decision.
- Approving leave with a pattern writes the expected sessions.
- A fill does not schedule over approved leave that has no entries.
- Ghosting, all three branches of the rule, because it is the part most easily
  got subtly wrong: a part-timer on leave gets **no** ghost on their
  non-working days; a clinician whose pattern covers a session that approval
  did not write **does** get one; a clinician with no pattern rows at all gets
  them across the range.
- A clinician outside their date window is absent from a fill, blank on the
  grid, and written no leave.
- Deleting a clinician with only unpublished entries succeeds and removes
  them; any published entry refuses and names the count.
- `1-6,9-12` parses; out-of-range values are refused at save.
- The grid's query count does not grow with the resolver's new inputs.

## Out of scope

- Pending leave influencing the fill engine.
- Automatic repair of damaged pattern data — the values were overwritten in
  place and cannot be recovered.
- Distinguishing "not yet started" from "left" from "does not work" on the
  grid; all three render blank.
- Frontend Phases 2 and 3 (mobile day view; drag-and-drop and keyboard
  navigation), which remain specced and unstarted.
