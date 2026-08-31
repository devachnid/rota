# Frontend Phase 2 — Mobile

**Date:** 2026-08-31
**Status:** Approved design, pre-implementation
**Builds on:** frontend Phase 1 (`2026-08-23-frontend-phase1-design.md`) and the
post-deployment fixes (`2026-08-30-rota-fixes-design.md`), both merged.

## Purpose

Phase 1 built a design system and applied it to every screen, and deliberately
deferred mobile. That deferral is visible in the stylesheet: 988 lines of CSS
containing no width-based media query at all. The only responsive behaviour in
the app is `overflow-x: auto` on wide tables, which is a considered answer for
the week grid and the reports and a poor one for the two screens a GP actually
opens on a phone.

This phase adds the day view the practice asked for, rebuilds My Schedule for a
phone, and gives the app a navigation that works on a narrow screen. It changes
no scheduling logic.

## Scope

**In:** the day view (new), My Schedule (rebuilt), the navigation (bottom tab
bar below 640px), and one extraction in `rota/views/grid.py` to stop the day
view duplicating the grid's cell rules.

**Out:** the week grid and the four report screens. Both already scroll
sideways below their minimum width, which is the answer Phase 1 chose for them
on purpose — `.grid-wrap` at `components.css:277` and `.table-scroll` at
`screens.css:141`. Phase 3 (drag-and-drop, keyboard navigation, inline editing)
is unchanged and still separate.

## Global constraints

Inherited unchanged, and every one of them is load-bearing:

- **No build step, no node, no preprocessor, no new dependencies.** A solo GP
  maintains this.
- Django 5.2 LTS, htmx, Python 3.13, SQLite WAL.
- Every colour comes from `static/css/tokens.css`. No hex literal may appear in
  `components.css` or `screens.css`; `tests/test_chrome_contrast.py` enforces it.
- Three-state dark mode: bare `:root`, then
  `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }`,
  then `:root[data-theme="dark"]`.
- WCAG AA: 4.5:1 for text, 3:1 for the visible boundary of any UI component.
- No pre-existing test may be edited.
- All schedule mutations stay in `rota/services/*`. This phase adds no mutations.

## Decisions

Each of these was settled during design and is not open for re-litigation
during implementation.

| Decision | Rationale |
|---|---|
| The day view shows the roster and **no staffing judgement**, for admins as well as GPs | A GP reading a roster can judge cover themselves. An app that says "covered" when it isn't is worse than one that says nothing. Warnings stay on the week grid, where they already are. |
| Day view layout: **one row per clinician**, AM and PM as columns, with a **pinned block above it** for the practice's critical session types | Keeps a person whole and reads as the week grid narrowed to one column, so anyone who knows the grid can already read it. Pinning costs two rows and answers the question that would otherwise cost sixteen. |
| The site rides **inside the chip** on the existing `.site-marker` disc | The vocabulary already exists (`components.css:478`). It costs about 1.1em of chip width rather than a column, which matters at 375px. 101 of 528 entries carry a site, so this is a frequent marker, not a rare one. |
| Clinicians in service who work no part of the day collapse to **one muted line** | Tells the reader the list is complete so nobody wonders whether someone has been lost, at a cost of one line rather than six rows. |
| Navigation: **bottom tab bar below 640px** — Week / Day / Me / More | Thumb-reachable, and it makes the day view a first-class destination rather than something reached by two taps. Above 640px nothing changes. |
| My Schedule order: **waiting on you → Today → four weeks → leave → your requests** | The current page puts the leave balance above the schedule, so a GP scrolls past how much leave they have left to find out where they are working tomorrow. |
| The agenda is **broken into weeks**, each headed with a session count | A week is the unit a rota is built and talked about in, and the count answers "am I doing my contracted sessions" — a question no other screen in the app answers. |
| **Closed days are omitted entirely** from the agenda; **open days you do not work show dashes** | Tom, during design: dashes make it clear that when you are off, you are off. A closed surgery is not you being off, so it is not your row. |
| The window stays at **four weeks** | Unchanged from the current page. |
| The Today box says **"Not in today"** when you have no sessions | Useful in its own right, and it keeps the box always present so its position never moves. |

## The day view

### Route

`/rota/day/` renders today. `/rota/day/<day>/` renders that date, where `<day>`
is `YYYY-MM-DD`. Both are named `day` and require login. A value that
`date.fromisoformat` rejects falls back to today rather than raising — matching
how `grid()` already treats `?week=`, so the two screens behave alike.

Non-admins see published entries only, the same filter the grid applies.
Neither role sees coverage, staffing or group warnings here.

### Layout, top to bottom

1. **Header** — the date in full, a previous/next stepper, and a count line
   reading `<n> in · <m> on leave`, where `n` is the number of roster rows
   and `m` the size of the "On leave" group. The stepper moves to the previous or next
   **open** day, skipping closed days and non-open weekdays, so a Friday's
   "next" is Monday.

2. **Closed days** — when the day is closed, or is not an open weekday, the
   body is replaced by a single statement naming the closure
   (`ClosedDay.name` when set, otherwise "Surgery closed"). The day note, if
   there is one, still renders. Nothing else does.

3. **Pinned block** — session types with `pin_on_day_view` set render first, as
   their own rows: clinician, part, chip. Ordered by session type name, then
   clinician name. When no type is flagged, the block is omitted entirely and
   nothing takes its place.

4. **The roster** — one row per clinician, ordered by name, in three columns:
   name, AM, PM. Each of the two cells is a chip or a dash. A chip carries the
   session type code, the site marker when the entry has a site, and the
   companion's name when the entry is half of a `companion_group` — the same
   three facts the grid's cell carries.

   The roster includes every clinician in service on that day who either has an
   entry or works at least one part, **except** those whose entries that day are
   all absence-category — they appear in "On leave" below instead, and in
   neither place twice. Someone on leave for one half and working the other
   stays in the roster, with the absence chip in its column.

   Full-day pairs (`allocation_group`) render as two chips, not one merged
   cell: the columns are AM and PM, and merging them would break the alignment
   that makes the layout readable.

5. **On leave** — clinicians whose entries that day are all absence-category,
   under their own subheading, with the absence chip.

6. **Not in** — one muted line listing, comma-separated, the clinicians in
   service who work no part of that day and have no entry: "Not in Tuesdays:
   Edward Pritchard-Rowlands, Nesreen Mayoub, …".

7. **Day note** — rendered for everyone, as it is on the grid.

Ghost leave chips follow the same rule as the grid, because both screens call
the same helper. Whether ghosts should be visible to non-admins at all is an
open question carried over from the previous phase; this phase does not settle
it, and inherits whatever the grid does.

### New field

`SessionType.pin_on_day_view`, `BooleanField(default=False)`, with a migration
and a line in `docs/admin/session-types.md`.

It is a configuration flag rather than something inferred, because inference
does not work here: the practice's per-slot coverage rules cover Duty, Urgent
**and** Routine, so any rule that pins "types with a per-slot coverage rule"
pins the bulk of the rota and defeats the purpose. Every other behaviour in this
app is driven by a flag on the session type, and this follows that pattern.

## My Schedule

The five-column table and its sideways scroller are removed, as is the bare
`<ul>` of requests. The screen becomes five sections in this order:

1. **Awaiting your response** — swaps a colleague has proposed. Rendered only
   when there is at least one, and the only section on the page carrying
   buttons.

2. **Today** — always rendered, so its position never moves. It shows today's
   sessions; or "Not in today" when you have none; or the closure when the
   surgery is shut.

3. **Next four weeks** — Monday-based blocks covering this week and the three
   that follow. The first block is headed "This week", the rest "Week of
   <j M>". Each heading carries a count on the right: `<n> sessions`, or "On
   leave all week" when every entry in that block's days is absence-category.

   Each block lists **every open day** in it — closed days and non-open
   weekdays are omitted, not shown as empty. A row is the date, then AM and PM
   as chip-or-dash. A day you do not work at all is a row of two dashes. Leave
   days render at reduced emphasis.

4. **Leave** — one compact four-cell strip (entitlement, taken, booked, left)
   rather than four large stats. It is a reference number, not a headline.

5. **Your requests** — pending leave and open swaps as rows carrying a status,
   in the same visual language as the agenda.

The structure holds at every width, so there is no separate desktop layout.

## Navigation

Below 640px the top `.nav` is hidden and a fixed bottom bar replaces it:

- **Week** → `/rota/`, **Day** → `/rota/day/`, **Me** → `/me/`, and **More**.
- **More** is a `<details>` opening upward, holding Requests and Assisted fill
  (admin only), Reports, the signed-in email, and Log out.
- Active state reuses the existing `request.path` comparison from `base.html`.
- `body` takes bottom padding equal to the bar's height so content clears it.
- Touch targets are at least 44px. The bar is a `<nav>` with an accessible
  label, and focus is visible on every item.

Above 640px the bar is hidden and the top nav is untouched, so the desktop
rendering does not change at all.

No JavaScript is added. `<details>` provides the disclosure natively, and
`static/js/theme.js` is not touched.

## Architecture

`grid()` is a 152-line function, and the part the day view needs is the cell
precedence at `rota/views/grid.py:85-118`: entry, then ghost leave, then off,
then empty — plus the two clauses that guard the ghost, one for the contractual
window and one for closed days. Those clauses cost three review rounds to get
right in the previous phase.

**Extract exactly that, and nothing else.** A new function takes a clinician, a
day, a part, and the already-prefetched context (the entry map, the
`AvailabilityResolver`, the closed-day set, the companion map) and returns the
cell dictionary both screens render. It performs no queries of its own.

`grid()` calls it in its existing loop and keeps everything else — groups, the
locum row, warnings, week headers, publish range. The day view calls it per
clinician.

The alternative of giving the day view its own query was rejected: it would
create a second answer to the question the entire previous phase existed to
give one answer to. Extracting the whole day assembly was also rejected, as
that refactors the application's main page immediately after it came through
five rounds of review, for no gain the narrower extraction does not already
deliver.

**New files:** `rota/views/day.py`, `templates/rota/day.html`, and the extracted
helper. A `/* ---- day view ---- */` section in `screens.css`, a `.tabbar`
component in `components.css`, and one `@media (max-width: 640px)` block.

## Testing

The failure this project keeps hitting is **inert work that looks finished**:
CSS rules written correctly that never apply, and tests that confirm themselves.
Phase 1 shipped four defects of exactly that shape. So:

- The extracted helper gets a unit test per precedence branch — entry present,
  ghost warranted, ghost suppressed by the window, ghost suppressed by closure,
  off, empty.
- **The grid's existing tests must pass unchanged.** They are the regression net
  for the extraction; if the helper alters behaviour, they fail.
- Day view: the pinned block present and absent, a closed day, roster ordering,
  the "not in" line, published-only for non-admins, and no warnings for either
  role.
- My Schedule: section order, closed days absent from the agenda, dashes
  present on unworked open days, the per-week session count, "On leave all
  week", and "Not in today".
- **A test that parses `screens.css` and asserts the `.tabbar` rules sit inside
  the `max-width: 640px` block.** This is the specific guard against a rule that
  is written but never applies.
- Query-count tests on both screens, as the previous phase added for the grid.
- A live measurement at 375px against the running app before the branch is
  called done. Reasoning about layout has been wrong here before; the browser
  found a defect in Phase 1 that review did not.

## Prerequisite, and it is configuration rather than code

Two session types share the code `Routine` — "Routine" (blue-soft) and
"Routine - PMC" (amber-soft). Templates render `session_type.code`, so on screen
they are the same word and **only the colour distinguishes them**, which is
precisely what the design system forbids: colour is a recognition aid, never the
sole signal. The site marker rescues it wherever the entry carries a site, but
not otherwise.

Giving the branch type its own code in `/admin/` fixes it, costs one edit, and
is worth doing before this phase is judged on screen.

## Deferred

- **Whether ghost leave chips should be visible to non-admins.** Carried over
  from the previous phase and still undecided. The day view inherits the grid's
  behaviour either way, so settling it later changes both screens at once.
- **Phase 3** — grid interaction: drag-and-drop assignment, keyboard
  navigation, inline editing.
