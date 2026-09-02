# Day to day

Most of this is done from the app itself rather than `/admin/`. The admin
entries exist for correcting things and for looking at history.

## Assisted fill

`/rota/fill/` — pick a date range, run it.

**What it does first:** deletes every entry in the range that is **unpublished
and not manually set** — that is, its own previous drafts. It never touches a
published entry or one an admin placed by hand, so re-running is safe and
repeatable. That is also why there is no confirmation step.

**Then it runs six passes in order:**

1. **Recurring commitments** — personal fixtures, never overwritten
2. **Trainee VTS** — anchored sessions protected before anything competes
3. **Coverage rules** — in `priority` order, lowest first
4. **Mentoring** — pairs each trainee with an available trainer
5. **Trainee SDL** — placed where it costs least cover
6. **Default fill** — only if you tick the box

Order is the mechanism: an earlier pass takes people, and later passes work with
whoever is left.

**Everything it creates is a draft.** GPs see nothing until you publish the week
from the grid.

### Reading the unfilled list

The result lists what it could not place and why. The reasons map directly to
configuration:

| Reason | Usually means |
|---|---|
| **no eligible clinician** | Nobody available *and* eligible. Check [pattern slots](availability.md#pattern-slots) first, then the type's [restrictions](session-types.md#allowed-clinicians-and-allowed-groups) |
| **anchored slot unavailable** | A trainee's anchored VTS session is one they do not work, or are already busy in |
| **quota unfilled this week** | A per-week or per-month rule could not place its full quota |
| **no session with trainer free** | No trainer was free in a session the trainee was also free |
| **no free session** | The trainee had no free session left for SDL — earlier passes took them all |

A long list of "no eligible clinician" across every rule almost always means
pattern slots are missing rather than that the rules are wrong.

## Rota entries

`/admin/rota/rotaentry/` — the assignments themselves. Normally edited by
clicking a cell on the grid; the admin view is for bulk corrections and for
seeing the fields the grid hides.

- **Day / Part / Clinician / Session type** — who is doing what, when.
- **Site** — where. Auto-stamped from the commitment or the type's default site
  unless set by hand.
- **Note** — free text on this one entry, shown on the cell.
- **Is published** — whether GPs can see it. Set in bulk by publishing a week
  from the grid.
- **Manually set** — marks the entry as placed by a human. **Assisted fill will
  not delete or overwrite it.** Set automatically when an admin edits a cell; if
  you want the fill engine to take an entry back over, untick this.
- **Allocation group** — links one clinician's AM and PM into a full day, so
  changing one half correctly splits the pair.
- **Companion group** — links **two clinicians'** entries in a paired session,
  such as a trainee and their trainer in mentoring. Distinct from allocation
  group, which is one person's two halves.
- **Fill reason** — which pass placed it, for tracing an unexpected assignment.

## Warnings on the grid

The red strips in a day's header come from **three separate sources**, so if you
want to silence one, you need to know which:

1. **Coverage warnings** — "No Duty cover (AM)". From coverage rules with
   frequency **Per slot** only; per-week and per-month rules are not checked
   this way, because being short one session on a Tuesday is not a problem when
   the quota is weekly.
2. **Staffing warnings** — "Only 1 clinical GP(s) (AM)". From [minimum clinical
   per session](practice-settings.md#minimum-clinical-per-session), counting
   clinical-category entries only.
3. **Group warnings** — "Salaried: 2/3 in (AM)". From a group's [min per
   session](people.md#min-per-session), counting non-absence entries.

Closed days generate no warnings at all.

Where a coverage warning has a matching locum requirement, the warning says so —
"No Duty cover (AM) — locum advertised" — so you can tell an unaddressed gap
from one you are already working on.

## Locum requirements

`/admin/rota/locumrequirement/` — tracks a gap you are trying to fill
externally, through three states:

**Possibly needed → Advertised → Booked.**

Add one from the "Need" row at the bottom of the grid. The status shows as a
badge and appends to the matching coverage warning, so the grid distinguishes
"nobody has looked at this" from "an agency is on it".

- **Details** — free text: which agency, what rate, who you called.
- **Clinician** — set when a specific locum is booked.
- **Rota entry** — the entry created when the booking is confirmed.

A **booked** requirement is protected: it cannot be unbooked or rebooked out
from under itself by a later fill. Requirements at the earlier two statuses can
step back freely.

## Leave

Not managed here. Leave is requested and approved in BreatheHR and read into
the rota every fifteen minutes — see [Leave from Breathe](breathe.md). Swaps
are still managed here.

## Swap requests

`/admin/rota/swaprequest/` — a GP proposes exchanging one of their sessions with
a colleague's.

Four states, labelled in the admin as you would read them:
**Awaiting colleague → Awaiting admin → Applied**, or **Declined** at either
step. The colleague accepts first, then an admin approves — so nobody's rota
changes without both the other clinician and an admin agreeing.

A decided swap cannot then be declined; once it is Applied or Declined it is
final, and a correction is a fresh change on the grid.

Swaps exchange **session type, site, note and full-day grouping between the two
entries** — the people stay where they are and the work moves. That is why both
clinicians must normally work both sessions involved, and why a full duty day
swaps as a whole rather than leaving someone with half of it.

Both entries become **manually set** afterwards, so a later assisted fill cannot
undo an agreed swap.

## The audit log

`/admin/rota/rotaentrylog/` — **read-only**, every field.

One row per change: what day and part, which clinician, who did it, what action,
and a free-text detail such as `ROUT -> DUTY`.

Clinician name is stored as **text, not a link**, so the log still reads
correctly after a clinician record changes. For a swap, one clinician's name is
on the row and the other appears in the detail.

Nothing writes to this except the app, and nothing should delete from it.
