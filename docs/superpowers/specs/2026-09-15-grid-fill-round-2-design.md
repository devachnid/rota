# Grid and fill, round 2 — design

**Date:** 2026-09-15
**Status:** approved in conversation; spec for review
**Branch:** `feature/grid-fill-round-2`

Five changes from Tom's use of the rota on staging, four to the week grid
and one to the assisted fill screen. One of them restructures how the grid
is built — the page shows a run of weeks rather than one — and the other
four ride on the same files, so they are specified together. The sixth
request from the same conversation, a per-clinician recurring aim, is a
new subsystem and has its own spec:
`2026-09-15-personal-requirements-design.md`.

## Decisions made in conversation

1. **The grid renders a fixed window of eight weeks** — one before the
   anchor week and six after — and reaches beyond it by reloading with the
   anchor moved. Not infinite loading, not the whole horizon.
2. **Sessions are marked as entered into the clinical system from a
   "ticking mode"** on the grid: click a chip, it flips, no form. Not a
   tick box in the cell form, not a whole-week button.
3. **A marked session is struck through, and only rota admins see it.**
   Non-admins see no difference anywhere, to avoid clutter and the
   "cancelled" misreading.
4. **The fill screen's default start is the first week that is under half
   filled**, counting working sessions against entries, from next Monday.
   Not "the week after the last fill run", not "the first coverage gap".
5. **Clinician order is an integer on the clinician**, edited inline on the
   admin list like group order. Grid and day view follow it; dropdowns and
   reports stay alphabetical.
6. **OFF appears only on an in-service clinician's usual non-working
   half-day.** Closed days and days outside someone's dates stay blank. The
   day view and My Schedule keep their dash.

## Global constraints (unchanged from the project)

- No build step, no node, no new dependencies.
- Every colour comes from `static/css/tokens.css`; `components.css` and
  `screens.css` carry no colour literals (a test greps for them).
- Exactly one width media query, `@media (max-width: 640px)`.
- `cell_state()` is the single answer to "what does this cell show". No
  screen re-derives it.
- Availability never fails open. Nothing here touches `available()`.
- No pre-existing test assertion is weakened. Assertions whose subject
  changes are re-pointed with their rationale rewritten; none is deleted.
- Every mutation runs inside `transaction.atomic()` and writes one audit
  line through `rota.services.entries._log`.

---

## 1. The grid shows a run of weeks

**Problem.** `/rota/` renders one Monday-to-Friday week and two buttons.
Building a rota four to six weeks ahead means paging through it a week at
a time, and every page has to be re-read from the left edge.

### The window

- The view still reads `?week=YYYY-MM-DD` and snaps it to a Monday; that
  Monday is the **anchor**. Absent or malformed, the anchor is today's
  week. The fill screen's "Review on the grid" link and the staffing
  report's day links keep working unchanged.
- The page renders eight weeks: anchor − 1 week through anchor + 6 weeks.
  Each week contributes the practice's open weekdays, as now; `days` is
  the flat, date-sorted list across the window. The `min()`/`max()`
  discipline in the view stays — `open_weekday_list()` preserves input
  order and may be empty — and per-week slices are taken from the sorted
  list, never by position.
- Every query that was `day__in=days` or a range over the week widens
  naturally: entries, companion pairs, absences, closed days, day notes,
  locum requirements. Non-admins still receive published entries only.
- The row-building loop moves out of `rota/views/grid.py` into a new
  `rota/services/grid.py` (`build_window(anchor, is_admin, user)` returning
  weeks, day headers, sections and locum cells; `build_row(...)` for one
  clinician). Section 2 needs to render one row on its own, and a
  142-line view that also assembles cells is the wrong place for it.

### The toolbar

- **Earlier** and **Later** replace Prev and Next. Each reloads with the
  anchor moved by four weeks, so successive windows overlap by four and no
  week can be skipped.
- **Today** is new. If today's column is on the page the button scrolls to
  it without a reload (script, below); otherwise it is a plain link to
  `?week=<today>`. It renders as a link either way, so it works without
  script.
- The date picker and Go stay. Propose swap stays.
- **Publish week leaves the toolbar** and goes into each week's header
  cell, below. The per-week ceiling warning line under the toolbar goes
  with it.
- The page `<h2>` and the table caption read "Weeks of 7 Sep – 26 Oct".

### Week markers

- The `<thead>` gains a **third row above the two it has**, one `<th
  class="grid-week" scope="colgroup">` per week, `colspan` = that week's
  open days × 2. It stays inside the one sticky `<thead>`: the CSS comment
  in `components.css` explains why sticking rows individually breaks, and
  a third row changes nothing about that.
- Each week cell carries: "Week of 14 Sep"; for admins, "3 drafts" when
  the week holds unpublished entries and the **Publish** form posting
  that week's `monday`..`week_end` to `/rota/publish/` (shown only when
  there is something to publish); any `week_warnings()` for that week; and
  `is-anchor` on the anchor week's cell so the script can find it.
- The first column of each week — the week cell, the day cell, the AM part
  cell, and every body cell in that column, merged or not — carries
  `week-start`. CSS gives it a 2px left border in `var(--muted)` — the
  1px `var(--hairline)` used elsewhere is too faint to read across a
  25-row table — so the boundary runs the full height of the table, not
  just the header. `border-collapse: separate` means the border sits
  inside the cell and costs no layout.
- Today's day cell, its two part cells and its body cells carry
  `is-today`. The header cells take `var(--accent-soft)` as ground; body
  cells take a 1px inset ring of `var(--accent)` on the `<td>` so the tint
  of the chip inside is untouched. This is the marker the Today button
  scrolls to.
- Closed-day styling, `mine` rows and the editing ring are unchanged and
  their cascade tests are extended for the two new classes rather than
  rewritten.

### Width

- The table's floor changes from one fixed length to one derived from the
  column count. The template sets `style="--cols: {{ cols }}"` on
  `<table>`, where `cols` is the number of half-day columns in the window,
  and `components.css` declares `min-width: calc(5.5rem + var(--cols) *
  3.5rem)`. 3.5rem is exactly what the old 42rem floor gave each of ten
  columns after the 5.5rem name column, so a one-week window would render
  as it does today and an eight-week one is eight times wider than the
  pane. `width: 100%` and `table-layout: fixed` stay.
- The cascade test that asserts a `>= 40rem` `min-width` on `.table-grid`
  is re-pointed: the floor must be a `calc()` over `--cols` with a
  per-column term of at least 3.5rem, and the comment above it is
  rewritten to say so. The rule that no width may be set on `.grid-day` or
  `.grid-part` stands, and `.grid-week` is added to it.
- `.grid-wrap` already scrolls both axes and is the sticky containing
  block. Nothing in `screens.css`'s pane sizing changes.

### Script

`static/js/grid.js` grows from one job to three, each in its own function:

- **Anchor on load.** If `sessionStorage` holds `grid-scroll:<window
  start>` — written below — restore the pane's `scrollLeft` from it and
  delete the key. Otherwise set `scrollLeft` so the `.grid-week.is-anchor`
  cell's left edge sits at the right edge of the frozen name column.
- **Remember before a refresh.** On `htmx:beforeRequest` for any request
  from inside `.page-grid` whose target is not `#modal`, and on
  `pagehide`, write the pane's `scrollLeft` under the key above. Every
  cell save answers `HX-Refresh: true`, which reloads the same URL, so the
  window start matches and the admin lands where they were.
- **Today.** If a `.is-today` header cell exists, the Today link's click
  is intercepted and the pane scrolled to it; otherwise the link is
  followed.

### Query cost

- `day_warnings()` runs one set of queries per day. Eight weeks makes that
  forty sets. The function gains an optional `bundle` argument: the
  entries for the day, the per-slot coverage rules, the ceiling-carrying
  session types, the groups with minimums and the practice settings, all
  fetched once by `build_window()` and sliced per day. Without it the
  function fetches as it does now, so the dashboard, staffing report and
  day view are untouched.
- A query-count test renders the grid at one week and at eight and asserts
  the count is the same, so the window cannot regress into per-day
  queries again.

### Tests

- `test_grid_view.py`: the week-snapping test becomes an anchor-snapping
  test; new tests for the eight-week span, the four-week step of Earlier
  and Later, a week cell per week with the right `colspan`, the Publish
  form present only on a week with drafts and posting that week's range,
  `week-start` on the first column of every week and nowhere else,
  `is-today` on today and nowhere else, and the caption's range.
- `test_grid_pane.py` and `test_accessibility.py` stand as written; the
  third header row keeps `scope="colgroup"`.
- `test_css_cascade.py`: the floor assertion re-pointed as above; new
  assertions that `.week-start` and `.is-today` do not touch
  `position`/`top`/`left`/`z-index` and that the today ring is inset.
- A query-count test as above.

---

## 2. Ticking mode: entered into the clinical system

**Problem.** After a week is published the rota administrator keys each
session into the clinical system's appointment screen. On the sheet they
struck through each cell as they went. Nothing here records that step, so
the admin cannot tell where they got to.

### Data

- `RotaEntry` gains `entered_at` (nullable datetime) and `entered_by`
  (nullable FK to the user, `SET_NULL`). A timestamp rather than a
  boolean: "when was this keyed in" is the audit question, and the
  tooltip can answer it. Migration `0030`.
- `rota.services.entries.set_entered(actor, entry, on)` writes both fields
  (or clears them), logs `entered` / `unentered` with the session code,
  and is the only writer.
- **What clears it.** `assign()` on an existing entry clears the mark when
  the session type or the site changes; a note-only save keeps it. Both
  swap kinds clear it on every entry they touch. A fill re-run deletes and
  recreates its own drafts, so the mark goes with the draft; published and
  manually-set entries are not touched by a re-run and keep it. `clear()`
  deletes the entry and the mark with it. `publish_range()` does not
  touch it.
- `cells.one_block()` adds "same entered state" to its merge rule, so a
  day with one half entered shows two chips.

### The mode

- Ticking mode is a URL flag, `?tick=1`, not a script state. Admin only;
  the flag is ignored for everyone else. The toolbar shows a **Ticking
  mode** link that toggles the flag on the current URL, rendered as a
  pressed button (`aria-pressed="true"`) while on. Earlier, Later, Today
  and the date form carry the flag through. Because `HX-Refresh` reloads
  the current URL, the mode survives a Publish.
- While on, a line under the toolbar reads "Ticking mode — click a session
  to mark it entered in the clinical system; click again to unmark. Turn
  off to edit cells." The `<body>` carries `is-ticking`.
- In ticking mode a cell holding an entry renders `hx-post="/rota/entered/"`
  with `hx-vals` of clinician, day and part (`DAY` for a merged chip),
  `hx-target="closest tr"`, `hx-swap="outerHTML"`, instead of the cell
  form's `hx-get`. Empty cells, absence chips and closed days render no
  htmx attributes at all in this mode. Day headers and the locum row are
  unchanged.
- `POST /rota/entered/` (`edit.entered`, `@admin_required`,
  `@require_POST`, `@parse_errors_as_400`): resolves the entries for the
  parts given; if every one is entered, clears them all, else marks them
  all. It then renders that clinician's row for the window through
  `build_row()` and returns it. No `HX-Refresh`, so the pane does not
  move. Marking a half of a merged day cannot happen (the chip posts
  `DAY`), and marking one half of an unmerged day never merges it, because
  the merge rule now sees the difference.
- The row template becomes an include, `rota/_grid_row.html`, used by the
  page and by this response, so there is one row markup.

### Look

- For admins only, the chip of an entered session gains `is-entered`.
  `components.css`: `text-decoration: line-through; text-decoration-color:
  var(--chip-fg); text-decoration-thickness: 2px`. The tint, the draft
  hatch, the clash ring and the note dot are unaffected.
- The cell tooltip prepends "Entered Fri 12 Sep 14:02 by TH — " using the
  actor's clinician initials, or their email when they have no clinician.
- Non-admins see nothing: `cell_state` still carries `entered`, but the
  templates only render the class and tooltip under `is_admin`. The day
  view and My Schedule do not render it at all.

### Admin

- The rota entry admin's list shows `entered_at`, filters on an "Entered"
  yes/no filter, and puts the two fields read-only in the "State"
  fieldset.

### Tests

- Service: `set_entered` writes and logs; `assign` clears on type change
  and on site change and keeps on note-only; both swap kinds clear;
  `delete_drafts` and `publish_range` leave it alone.
- `one_block` splits on differing entered state.
- View: `?tick=1` is ignored for a non-admin; a cell in ticking mode
  carries the post and no `hx-get`; empty cells carry nothing; the
  endpoint toggles both halves of a `DAY` post; the response is one
  `<tr>` with the new class; the toolbar link carries the flag.
- Rendering: `is-entered` present for an admin, absent from the same
  page for a non-admin; the tooltip text.
- `test_chrome_contrast.py` needs no entry: the strike uses the chip's own
  foreground.

---

## 3. The fill screen suggests the next week to fill

**Problem.** `/rota/fill/` defaults to next Monday. The rota is built four
to six weeks ahead, so the admin first pages through the grid to find the
next empty week, then types it in, every time.

### The rule

- From next Monday, the first week whose **filled share is under a half**:
  `filled * 2 < working`, where *working* is the number of (clinician,
  open day, part) cells the clinician works by pattern, is in service for
  and is not on Breathe leave for, and *filled* is how many of those hold
  any entry, draft or published. A week with no working sessions (every
  day closed) is skipped. The search stops at 26 weeks and falls back to
  next Monday.
- A few advance bookings, a booked locum or a hand-placed clinic leave a
  week well under half, so it is still picked. A week the fill has run on
  is over half unless the practice is mostly empty, in which case there is
  nothing to suggest anyway.

### Where it lives

- `rota/services/next_week.py`: `suggest(today) -> Suggestion(monday,
  working, filled, found: bool)`. One query each for active clinicians,
  pattern slots, absences over the horizon, closed days and entries;
  availability through `AvailabilityResolver`, open days through
  `calendar.is_open`. No fill machinery: the fill context is built for a
  run, not for a scan.
- `fill._base_context()` calls it for `start`; `end` stays `start + 27
  days`. The delete-drafts card shares the default as it does now.

### What the admin sees

- Under the date fields: "Suggested from Mon 12 Oct — the first week under
  half filled (3 of 48 sessions)". When nothing in 26 weeks is under half:
  "No week to <date> is under half filled; defaulting to next Monday."
  The dates stay editable.

### Tests

- Service: an empty rota suggests next Monday with `found`; a week with a
  couple of advance sessions is still chosen; a week at exactly half is
  not; a week with every day closed is skipped; the 26-week cap and
  fallback; leave reduces *working*; a query-count assertion.
- View: the default `start` in the rendered form follows the suggestion;
  the line's wording in both cases. `test_fill_form.py` keeps its
  checkbox assertion.

---

## 4. Clinicians in the admin's order

**Problem.** Rows within a group are alphabetical by full name while the
grid shows initials, so the order looks arbitrary and cannot be changed.

- `Clinician.display_order`, `PositiveIntegerField(default=100)`, help
  text "Rows within the group appear on the grid in this order, lowest
  first." `Meta.ordering = ["display_order", "name"]`, so nothing moves
  until an admin sets a value and ties stay alphabetical. Migration
  `0029`.
- `ClinicianAdmin`: `display_order` joins `list_display` after `group`,
  `list_editable` gains it (the `ClinicianGroupAdmin` pattern), and it
  sits in the "Who" fieldset after `group`.
- Followers: the grid's `Prefetch` orders explicitly by
  `("display_order", "name")`; `views/day.py`'s `order_by("name")` becomes
  the same. Every other `order_by("name")` — the cell form's partner and
  locum dropdowns, reports, requests, the Breathe link list, the fill
  context — stays alphabetical, on purpose: a picker is scanned by name.
- `docs/admin/people.md` gains a "Display order" entry under Clinicians.

### Tests

- Model ordering; the grid renders two clinicians in the same group in
  display order, then name; the day view agrees; the admin changelist
  carries the editable field.

---

## 5. OFF on a usual non-working half-day

**Problem.** A part-timer's day off renders as a blank cell, the same as a
closed day or a clinician outside their dates. Users read blank as
"nothing has been put here yet".

- `cell_state` gains `off_pattern`: true when there is no entry, the
  clinician does not work the session, they are in service that day, they
  have a pattern at all, and the day is not closed. The existing `off`
  stays as it is, so nothing that reads it changes. A clinician with no
  pattern rows keeps blank cells — the dashboard already counts them, and
  a row of OFF would say the opposite of the truth.
- The grid's `{% elif cell.off %}` branch splits: `off_pattern` renders
  `<span class="chip is-off">OFF</span>` with `title="Not a working
  session"`; any other `off` renders the blank chip as now.
- `components.css`: the OFF chip carries `is-off is-not-working`; the
  second class gives it `background: var(--sunken)`, and the chip's
  fallback `--muted` foreground does the rest. The blank `is-off` chip
  stays transparent, so closed and out-of-window cells look as they do
  now. Muted on sunken is already a checked pairing in
  `test_chrome_contrast.py`; its description gains the OFF chip. The
  comment at the chip block and the docstring of `test_grid_rendering.py`
  that say "blank means not working" are rewritten: blank means closed or
  not employed; OFF means not working.
- The day view's dash and My Schedule's dash stay.

### Tests

- `test_cells.py`: `off_pattern` true for a slot with `works=False` and
  for a weekday with no slot; false on a closed day, outside the
  contractual window, with no pattern rows, and under an entry.
- `test_grid_rendering.py`: the non-working session shows OFF; a closed
  day does not; the `_chips` harness keeps matching.

---

## Documentation

- `docs/admin/day-to-day.md`: the grid section describes the window,
  Earlier/Later/Today, the week header and its Publish button, ticking
  mode and what clears a mark; the assisted fill section describes the
  suggested start.
- `docs/admin/people.md`: display order.
- `README.md`'s spec list gains this round.
- `docs/backlog.md`: a Settled entry per section, and the query-cost note
  under "Open — minor" about `day_warnings` is updated to say the grid
  now passes a bundle and the dashboard still does not.

## Order of work

1. Clinician ordering (section 4) — a field, a migration, two call sites.
2. OFF chip (section 5) — `cell_state`, one template branch, CSS,
   contrast.
3. Fill suggestion (section 3) — a service and a view line, independent
   of the grid.
4. The window (section 1) — the grid service, template, CSS, script,
   warnings bundle. The largest and the one everything after depends on.
5. Ticking mode (section 2) — fields, service, endpoint, row include, on
   top of the new grid service.

Each step lands with its tests and its docs, and `graphify update .`
afterwards as `CLAUDE.md` asks.
