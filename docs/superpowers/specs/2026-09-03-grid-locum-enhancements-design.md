# Grid, leave and locum enhancements — design

**Date:** 2026-09-03
**Status:** approved in conversation; spec for review
**Branch:** `feature/grid-locum-enhancements`

Seven bounded changes from Tom's first days with the Breathe integration on
staging. None restructures anything; each changes a flow that already exists.
They are specified together because they run together, and because three of
them share one piece of plumbing (a cell knowing it is on leave even when it
holds an entry).

## Decisions made in conversation

1. **A Breathe clash is visible to everyone, type included.** A rostered
   session on someone Breathe says is off shows a marker on the cell and the
   kind of leave in its tooltip, to every user who can see the cell. Drafts
   remain admin-only because non-admins never receive drafts.
2. **The "Other" leave reason is visible to everyone** as the chip tooltip.
   Sickness type is never stored, so "Sick" can never say more than "Sick".
3. **Deleting drafts offers both scopes** — all unpublished, or only the fill
   engine's own — and always shows a preview before anything is deleted.
4. **"Need approved" sits second**: Possibly needed → Need approved →
   Advertised → Booked. Approval is for seeking a locum, not for a booking.

## Global constraints (unchanged from the project)

- No build step, no node, no new dependencies.
- Every colour comes from `static/css/tokens.css`; `components.css` and
  `screens.css` carry no colour literals (a test greps for them).
- Exactly one width media query, `@media (max-width: 640px)`.
- `cell_state()` is the single answer to "what does this cell show". No
  screen re-derives it.
- Availability never fails open. Nothing here touches `available()`.
- No pre-existing test assertion is weakened. Assertions whose subject
  changes (a message, a title) are re-pointed; none is deleted.
- The Breathe API key appears in no file. Nothing here talks to Breathe.

---

## 1. Notes get a visible marker

**Problem.** `RotaEntry.note` reaches the grid only as part of the cell's
`title` attribute. Nothing on screen says a note exists; on a phone nothing
ever reveals it.

**Design.**

- The chip gains `has-note` when, and only when, `entry.note` is non-empty.
  `fill_reason` alone does not qualify: it is the engine's diagnostic
  ("default fill", "commitment"), not something a person wrote.
- `.chip.has-note::after` draws a 6px dot at the chip's top-right corner,
  absolutely positioned so it costs no layout — the chip is `overflow:
  hidden` with `text-overflow: ellipsis`, and a text glyph would be the
  first thing eaten on a narrow column. Colour is `var(--chip-fg,
  var(--muted))`, the cell's own foreground, so it holds on every tint in
  both themes with no new token. `.chip` gains `position: relative`.
- The marker renders wherever a chip does: grid, day view (roster, on-leave
  and pinned block), My Schedule (today and week rows).
- Phones have no hover, and the day view and My Schedule are the phone
  screens, so those two **also print the note text** beneath the chip: a
  `.day-note-text` line on the day view sharing `.day-partner`'s rule
  (muted, `--fs-xs`), and an `.ms-note` span **inside `.ms-cells`** with
  `flex-basis: 100%`, so it wraps onto its own line beneath the two chips,
  aligned with the cells column rather than the date. `.ms-cells` already
  wraps; `.ms-day` is untouched.
  The grid keeps its `title` and adds nothing else — the day view is one
  tap away and is where a phone reads a day.
- No audience change: the title already showed notes to everyone.

**Tests.** `has-note` present iff note (grid, day, Me); note text rendered on
the day view and My Schedule; cascade test that `.chip.has-note::after`
exists, sets `content`, and uses no colour literal (the existing grep covers
the literal); `.chip` is `position: relative`.

## 2. Clashes say who, and mark the cell

**Problem.** `_breathe_conflicts()` in `rota/services/warnings.py` produces
"1 rostered on Breathe leave (AM)". It names nobody. And `cell_state()`
forces `on_leave = False` whenever an entry exists, so no screen can mark
the cell — the fact never reaches it.

**Design — the plumbing (one change, three consumers).**

`AvailabilityResolver._covering()` becomes public as `covering(clinician_id,
day, part) -> (kind, reason) | None`. It already exists; it is the one place
both `leave_type()` and `on_leave()` read the overlay.

A pure helper `leave_label(kind, reason) -> str` in `rota/services/cells.py`:

| kind | reason | label |
|---|---|---|
| holiday | any | `Holiday` |
| sickness | always blank | `Sick` |
| other | `Jury service` | `Other leave: Jury service` |
| other | blank | `Other leave` |

Anything else (the model constrains kind to those three) falls back to
`kind.capitalize()`.

`cell_state()` changes:

- `on_leave` is computed **regardless of whether an entry exists**. It was
  gated on `entry is None`; that gate is what hid clashes.
- `absence` (the chip to render when there is no entry) is unchanged and
  still only computed for an empty cell — an entry still beats leave for
  what the cell *shows*.
- New key `leave_label`: the label of the covering absence when `on_leave`,
  else `None`. Never goes through the mapping, so an unmapped kind still
  labels.
- New key `clash`: `entry is not None and on_leave`. A closed day does not
  suppress it — an entry means someone is rostered, closed or not.

**Consumers.**

- **Cell (everyone).** The entry chip gains `is-clash`: `box-shadow: inset 0
  0 0 2px var(--danger)`, a non-text cue that survives both themes and the
  draft hatch. The cell `title` gains `On Breathe leave: <label>`, joined to the
  existing note/partner text with ` — ` when that text is non-empty.
- **Header line (admin, as now).** Message becomes
  `On Breathe leave but rostered (AM): TH (Holiday), JS (Sick)` — initials
  sorted, each with its label in parentheses. Initials, not names, because it
  lives inside one day column of the grid. `Warning.code` stays `"breathe"`.
- **Day view.** A clinician whose worked parts are all covered — by leave or
  by a clash — files under **On leave**, where the on-leave table already
  renders entry chips; the chip carries `is-clash` there. The "N in · M on
  leave" line follows. Breathe says they are off; the section says so, and
  the marker explains the session.
- **My Schedule.** `_is_leave_cell()` needs no change — it reads `on_leave`.
  A clashing day therefore takes the `is-leave` row style with its chip
  marked, and a week of clashes reads "On leave all week": the truth, with
  the marker making the sessions the visible anomaly.
- **Fill and swaps** read the resolver directly, not `cell_state`; nothing
  changes for them.

**Two leftovers from PR #6 close here, because they live in these functions.**

- `day_warnings(day, include_drafts=True, resolver=None)`: when a resolver
  is passed, `_breathe_conflicts` uses it instead of building one. The grid
  passes its week resolver. That removes the three queries per open day the
  warning currently costs. Known bound: the grid's resolver holds active
  clinicians, which is who the grid shows; an inactive clinician's entry is
  invisible on the grid already.
- `_blocks()` in `my_schedule.py` guards `is_leave` with `is_open`, as
  `today_state` already does, so a closed day that carries a stray entry
  can no longer take the leave style.

**Tests.** `test_breathe_conflicts.py` re-pointed to the new message and
extended with a two-clinician case that checks ordering and labels. New:
`clash` and `leave_label` keys from `cell_state` (entry + leave, entry + no
leave, leave + no entry, unmapped kind still labels); `is-clash` on the grid
for admin and for a non-admin on a published entry; not on a draft for a
non-admin; the day view files a clash under On leave with the marker; My
Schedule's `_blocks()` does not mark a closed day; the grid's query count
does not grow with the number of open days.

## 3. The leave reason as a tooltip

**Problem.** Every Breathe chip says `title="From Breathe"`. The "Other"
kind carries a reason Breathe recorded and nothing shows it.

**Design.** The six chip sites (grid, day roster, day on-leave table, My
Schedule today + two week cells) render
`title="{{ cell.leave_label }} — from Breathe"`:
`Holiday — from Breathe`, `Sick — from Breathe`,
`Other leave: Compassionate — from Breathe`. Same `leave_label` as item 2, so
the tooltip on an empty cell and the tooltip on a clash can never disagree.

**Tests.** The ten existing `'title="From Breathe"'` references become
references to the new text. `test_grid_rendering.py:64` uses the title to
tell a chip apart from an entry — it switches to the `— from Breathe` suffix.
One new test per kind for the label text on a rendered chip.

## 4. Delete drafts, with a preview

**Problem.** There is no way to clear unpublished work except cell by cell,
or by re-running fill (which only clears its own drafts, and creates more).

**Design.**

A second card on `/rota/fill/`, **Delete drafts**, its own `<form>`:

- `scope`: `all` (every unpublished entry) or `fill` (unpublished **and**
  not manually set — the rule `run_fill()` already applies).
- `range`: `all` (no date bound) or `dates`, with `start`/`end` defaulting to
  the fill form's dates.
- First POST (no `confirm`) re-renders the page with a preview card:
  "128 drafts between 8 Sep and 5 Oct, 12 placed by hand" (or "all dates"),
  and a **Delete** button carrying `confirm=1` plus the same fields. Nothing
  is deleted on the first POST. This is the spec's preview rule for
  destructive actions; the fill re-run's exemption argument (it only removes
  what it made) does not apply to a button that can remove hand-placed work.
- Second POST deletes, flashes "Deleted 128 drafts" through
  `django.contrib.messages` (the swap views' pattern; `base.html` renders
  them), and redirects to `/rota/fill/`.
- URL `rota/drafts/delete/`, name `drafts-delete`, `@admin_required`,
  `@parse_errors_as_400`, `@require_POST`.

Service, in `rota/services/entries.py`:

```python
def drafts(start=None, end=None, *, include_manual) -> QuerySet
def delete_drafts(actor, start=None, end=None, *, include_manual) -> tuple[int, int]
```

`drafts()` is the single definition of "in scope"; the preview counts it,
`delete_drafts()` deletes it. `delete_drafts()` is atomic, returns
`(deleted, hand_placed)`, writes one `RotaEntryLog` row (`action="deleted
drafts"`, detail `2026-09-08..2026-10-05 (128 entries, 12 hand-placed)` or
`all dates (...)`), and **un-groups survivors**: any published entry whose
`allocation_group` or `companion_group` matched a deleted row has that field
set to `None`, so no half of a pair dangles. `run_fill()` calls
`delete_drafts(actor, start, end, include_manual=False)` in place of its own
`.delete()` — one deletion rule, not two — and so also logs.

Booked locum sessions are created `is_published=True` and are never in
scope. `LocumRequirement.rota_entry` is `SET_NULL` in any case.

**Tests.** Scope × range matrix (4 cases) on counts; preview POST deletes
nothing; confirm POST deletes and logs; published entries untouched;
hand-placed survives `scope=fill`; a deleted draft's published pair loses
its group; `run_fill` still clears exactly its own drafts; non-admin gets
403; GET is 405.

## 5. Locum status: Need approved

**Design.** `LocumRequirement.Status` becomes

```python
POSSIBLE   = "POSSIBLE",   "Possibly needed"
APPROVED   = "APPROVED",   "Need approved"
ADVERTISED = "ADVERTISED", "Advertised"
BOOKED     = "BOOKED",     "Booked"
```

Value `APPROVED` keeps `max_length=10`; the status half of migration
`0024_locum_status_and_covering` (shared with item 6) is an `AlterField` on
choices only, no data change.
Badge colour encodes progress in one family: red = possibly needed, **amber
outline** = need approved (`background: transparent; box-shadow: inset 0 0 0
1px var(--warning); color: var(--warning)`), amber filled = advertised,
green = booked. An outline rather than a fourth hue because `--accent` and
`--ok` are the same green in dark mode, so any green-ish fourth colour would
read as "booked". Coverage warnings gain "— locum need approved" through the
existing `get_status_display().lower()` path — no new machinery.

**Tests.** Choices order; `.badge.APPROVED` rule with tokens only; the
warning suffix; the form lists four statuses in order.

## 6. Who the locum covers

**Design.** `LocumRequirement.covering`: FK to `Clinician`, `null=True,
blank=True, on_delete=SET_NULL, related_name="+"`, help text "The
clinician this locum stands in for". Same migration as item 5
(`0024_locum_status_and_covering`).

- Form: a **Covering for** dropdown above Details, listing active
  clinicians **outside** the locum group, ordered by name, with a blank
  option. `save_requirement(..., covering=None)` refuses a locum-group
  clinician with `ValueError("Covering must be a clinician outside the
  locum group.")`, surfaced as the form's warning like the other refusals.
- Badge tooltip: `Covering Tom Hodges — Agency X` when set (the dash only
  when details are non-empty), else details as now.
- On booking, the created entry's note is `Covering Tom Hodges. <details>`
  truncated to 200, else `<details>` as now. So the grid cell says who the
  locum covers, and item 1's marker lights the booked cell.
- `LocumRequirementAdmin.list_display` gains `covering`. The grid's
  requirements query adds `select_related("covering")`.

**Tests.** Save and round-trip; note prefix on booking; refusal of a
locum-group clinician; the dropdown excludes locums; tooltip text.

## 7. Locums appear only when booked

**Design.** One rule in `rota/services/cells.py`:

```python
def shows_on_roster(*, is_locum: bool, has_entry: bool) -> bool:
    return has_entry or not is_locum
```

- **Grid.** For the locum group, a row appears only for a locum with at
  least one entry in the displayed days. The **Need** row is unchanged and
  renders regardless. `Clinician` rows for other groups are unaffected.
- **Day view.** Locum-group clinicians without an entry that day are skipped
  before the partition, so they appear in neither the roster, the on-leave
  table, nor the "Not in Tuesdays" line — which is where they pile up today.
  `active` is fetched with `select_related("group")`.
- **Untouched.** The cell edit form, the locum form's "Locum (required to
  book)" dropdown and admin list every locum — they need the full list.
- **Out of scope**, noted for later: the fairness pool (`fairness._in_service`)
  still includes active locums; with no pattern their weight is zero.

**Tests.** A booked locum shows on both screens; an idle locum shows on
neither and is absent from "Not in"; the Need row survives an empty locum
section; non-locum groups unaffected; query count on the day view unchanged.

## Documentation

- `docs/admin/breathe.md`: the new warning wording; the cell marker; the
  tooltip label.
- `docs/admin/day-to-day.md`: **Delete drafts** section after Assisted fill
  (both scopes, preview, log); the fill's "why no confirmation" sentence
  qualified; locum requirements now four states with the badge colours;
  the Covering field; locums shown only when booked.
- `docs/backlog.md`: remove the two PR #6 leftovers that close here.

## Order of work

Item 2's plumbing first (resolver, `leave_label`, `cell_state`), then items
2 and 3 together in the templates, then 1, then 5 + 6 (one migration), then
7, then 4, then docs. Roughly fifteen tasks, subagent-driven with per-task
review as before.
