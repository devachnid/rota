# Day to day

**Where:** sidebar › Records › Rota entries / Audit log / Locum requirements / Swap requests

Most of this is done from the app itself rather than `/admin/`. The admin
entries exist for correcting things and for looking at history.

## Assisted fill

`/rota/fill/` — pick a date range, run it.

**What it does first:** deletes every entry in the range that is **unpublished
and not manually set** — that is, its own previous drafts. It never touches a
published entry or one an admin placed by hand, so re-running is safe and
repeatable. That is also why the run itself has no confirmation step — the
Delete drafts card below, which can remove hand-placed work, does. That
clearing is written to the rota entry log as a "deleted drafts" line, even
when there was nothing to clear, so every run leaves a trace.

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

## Delete drafts

Also on `/rota/fill/`. Two choices, then a preview, then the deletion.

- **Which drafts** — every unpublished session, or only the fill engine's own
  (the rule the engine itself applies before a re-run: unpublished **and** not
  placed by hand).
- **Which dates** — every date, or a range.

**Preview** shows how many drafts that is and how many were placed by hand.
Nothing is deleted until you press **Delete** on that preview. Published
sessions are never deleted; a booked locum's session is published when it is
booked, so it is never deleted either. A published session that was paired
with a deleted draft — the other half of a full day, or a companion in a
paired session — keeps its own session but loses the pairing. One line goes
to the rota entry log per deletion, naming the range and the counts.

## Rota entries

`/admin/rota/rotaentry/` — the assignments themselves. Normally edited by
clicking a cell on the grid; the admin view is for bulk corrections and for
seeing the fields the grid hides.

On the grid, the cell you clicked is ringed while its form is open, so there
is no doubt which one is being edited. A day whose AM and PM would show the
same chip — same session type, same site, both published or both drafts, the
same leave clash and the same mentoring partner — is drawn as **one chip across
both columns**, however the two halves came to be (assisted fill, the import,
or placed one at a time); only the notes may differ, and then the tooltip
gives both. The day view draws such a day the same way, one chip across
its AM and PM columns. Click it on the grid and the form is for the whole
day. The **Applies to**
choice at the foot of every cell form — Whole day / AM / PM — opens on the
whole day for such a chip and on the half you clicked otherwise; to split a
day, pick the half to change and save, and the other half is left as it was.
Clear follows the same choice. The **Session** list is grouped
Clinical / Non-clinical / Absence, and an empty cell opens on the practice's
[default fill session type](practice-settings.md). Choose the practice's
mentoring type and a **With** field appears: pick the other half of the pair
(a trainee's trainer is offered first, and a trainer's only trainee) and the
same session is written to both rotas, linked, exactly as assisted fill does
it — the grid then shows "with …" on each cell and clearing either clears
both. If the other person already holds something else in that slot the form
says so and asks you to save again before replacing it.

- **Day / Part / Clinician / Session type** — who is doing what, when.
- **Site** — where. Auto-stamped from the commitment or the type's default site
  unless set by hand.
- **Note** — free text on this one entry. A dot in the chip's corner says
  one exists; the grid shows it on hover, and the day view and My Schedule
  print it under the session.
- **Is published** — whether GPs can see it. Set in bulk by publishing a week
  from the grid.
- **Manually set** — marks the entry as placed by a human. **Assisted fill will
  not delete or overwrite it.** Set automatically when an admin edits a cell; if
  you want the fill engine to take an entry back over, untick this.
- **Allocation group** — links one clinician's AM and PM into a full day, so
  changing one half correctly splits the pair. The grid does not read it:
  a whole-day chip is drawn whenever the two halves match, grouped or not.
- **Companion group** — links **two clinicians'** entries in a paired session,
  such as a trainee and their trainer in mentoring. Distinct from allocation
  group, which is one person's two halves.
- **Fill reason** — which pass placed it, for tracing an unexpected assignment.

## Warnings on the grid

The red strips in a day's header come from **five separate sources**, so if you
want to silence one, you need to know which:

1. **Coverage warnings** — "No Duty cover (AM)", or "Routine 3/4 (AM)" when
   some but not all of the count are placed. From coverage rules with
   frequency **Per slot** only; per-week and per-month rules are not checked
   this way, because being short one session on a Tuesday is not a problem when
   the quota is weekly.
2. **Staffing warnings** — "Only 1 clinical GP(s) (AM)". From [minimum clinical
   per session](practice-settings.md#minimum-clinical-per-session), counting
   clinical-category entries only.
3. **Group warnings** — "Salaried: 2/3 in (AM)". From a group's [min per
   session](people.md#min-per-session), counting non-absence entries.
4. **Breathe clashes** — "On Breathe leave but rostered (AM): TH (Holiday)".
   A published or drafted session on someone Breathe says is off. The cell
   itself is ringed for everyone; this header line is yours. See
   [Leave from Breathe](breathe.md).
5. **Ceiling warnings** — "Too many Urgent (PM): 2, max 1" or "Too many
   Urgent today: 3 sessions, max 2". From a session type's
   [ceiling](session-types.md#ceiling). The per-week ceiling has no day to
   sit on, so it appears on a line under the week toolbar instead: "Too many
   LARC this week: 3 sessions, max 2".

Closed days generate no warnings at all.

Where a coverage warning has a matching locum requirement, the warning says so —
"No Duty cover (AM) — locum advertised" — so you can tell an unaddressed gap
from one you are already working on.

## Locum requirements

`/admin/rota/locumrequirement/` — tracks a gap you are trying to fill
externally, through four states:

**Possibly needed → Need approved → Advertised → Booked.**

The badge colour follows: red, amber outline, amber, green. "Need approved"
is approval to seek a locum, before anyone advertises.

Add one from the "Need" row at the bottom of the grid. The status shows as a
badge and appends to the matching coverage warning, so the grid distinguishes
"nobody has looked at this" from "an agency is on it".

- **Details** — free text: which agency, what rate, who you called.
- **Clinician** — set when a specific locum is booked.
- **Covering for** — optional: the clinician the locum stands in for. Shown
  on the badge's tooltip, and written into the booked session's note
  ("Covering Tom Hodges. Agency X") so the grid cell says it too.
- **Rota entry** — the entry created when the booking is confirmed.

A **booked** requirement is protected: it cannot be unbooked or rebooked out
from under itself by a later fill. Requirements at the earlier three statuses can
step back freely.

A clinician who **has not yet started, or has finished** — their start date is
after the week, or their end date before it — has no row on the grid for that
week, and is not on the day view for a day outside their dates. Someone who
starts mid-week is on that week's grid with the earlier days blank. A session
of theirs in the period shown brings the row back, so it can be reviewed,
moved or removed: the admin is warned about such sessions when the dates are
saved, and the grid is where they are dealt with.

Locums appear on the grid and the day view **only in a period where they hold
a session**. An idle locum is neither a blank row nor a name on the "Not in"
line. The booking form and the admin still list every locum. Because an idle
locum has no row, there is no cell to click to give them a first session:
book them through a locum requirement from the Need row, which creates and
publishes the session.

**Locum bookings report** — `/reports/locums/` lists every booked requirement
in a date range (the last 30 days by default): the date and session, which
locum, who they covered, and what the covered clinician was off for — Breathe's
kind of leave where it has one, otherwise an absence session on the grid,
otherwise "No absence recorded". Filter by locum, by who was covered, and by
kind of absence. Visible to every clinician, like the other reports.

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

A GP proposes from **My schedule › Propose a swap**. The colleague list on that
page holds only clinicians with a login account — the colleague accepts the
swap themselves, so someone who cannot sign in can never be asked. If a GP says
the list is empty, or the page tells them *None of your colleagues has a login
account yet*, link the accounts to their clinician records: People ›
Clinicians › [User](people.md#user). Until then the page explains itself and
offers nothing to submit.

### Two kinds of swap

The app works out which kind a swap is from the rota — when it is proposed,
and again when it is approved:

- **Trading the work.** Both GPs already have sessions in every session
  involved — you both work Monday morning and one of you has Duty. What each
  does in them is exchanged: session type, site, note and full-day grouping.
  The people stay where they are.
- **Covering for each other.** Each GP has a session only in their own slot
  and none in the other's — I do your Monday morning, you do my Friday
  afternoon. The two entries change hands and keep what they are.

Anything in between is refused with a sentence naming the fact that breaks
both patterns (*Tom already has a session on Mon 7 Sep AM*). Whatever the
kind, each GP must still have the session they put forward, no paired
(mentoring) session may be involved, and neither GP may be on Breathe leave
for a session they would take on. A full duty day counts as a whole on either
side.

The propose form runs the same checks, so a colleague is never asked about a
swap that could not be applied as the rota stands.

### Approving

Two places do the same thing: the **Requests** page in the app's nav, and the
swap's own page here. Both show what applying would do (*Edward takes Tom's
Fri 11 Sep PM; Tom takes Edward's Mon 7 Sep AM*) or the problems standing in
the way, and both offer **Approve and apply** — only once the colleague has
accepted — and **Decline** with a comment. Approve changes the rota, writes an
audit row per session and stamps who decided and when.

The status is not editable by hand: it follows from those two buttons. A
decided swap cannot then be declined; once it is Applied or Declined it is
final, and a correction is a fresh change on the grid.

Every entry a swap touches becomes **manually set**, so a later assisted fill
cannot undo an agreed swap.

### Who is told

Each step emails the people it concerns, through the same relay as
invitations (nothing is sent when no relay is set up; the swap still
happens):

| When | Who gets an email | Where it points |
|---|---|---|
| A GP proposes | the colleague, Reply-To the proposer | My schedule, to accept or decline |
| The colleague accepts | the proposer; every active rota admin | My schedule; Requests |
| The colleague declines | the proposer, with the colleague's comment | My schedule |
| An admin applies or declines | both GPs, with the admin's comment | My schedule |

A GP with no login account, or no email address, is skipped. In the app, a
count appears on **My schedule** (and the phone's *Me* tab) while a swap awaits
that person's answer, and on **Requests** (and *More*) for an admin while one
awaits approval; the dashboard's Health card counts *Swaps awaiting your
approval* and links to Requests. The colleague can add a comment when
declining; the proposer sees it under *Your requests* on My schedule.

## The audit log

`/admin/rota/rotaentrylog/` — **read-only**, every field.

Every change to a rota entry writes an audit log entry: who, when, which cell,
and what changed.

One row per change: what day and part, which clinician, who did it, what action,
and a free-text detail such as `ROUT -> DUTY`.

Clinician name is stored as **text, not a link**, so the log still reads
correctly after a clinician record changes. For a swap, one clinician's name is
on the row and the other appears in the detail.

Nothing writes to this except the app, and nothing should delete from it.

## Feedback

`/admin/feedback/feedback/` — the bug reports and ideas people send from the
**Feedback** control in the app's header (or the **More** sheet on a phone).

Each row records what they chose (*Something's wrong* or *An idea*), what they
wrote, who they are, when, the page they were on, their screen size and
browser. The app fills all of that in; none of it is editable here. Nobody
can add a row from the admin — feedback comes from the app.

**Status** is yours: **New** when it arrives, **Seen** once someone has read
it, **Done** when it is dealt with. The dashboard counts the New ones. Select
several rows and use **Mark as seen** or **Mark as done** to move them
together.

**Admin note** is for admins only. It is never sent to anyone.

**Reply** is sent to the reporter by email when you press **Send reply**
under the form. The email carries your reply, quotes what they wrote, and has
your address as its Reply-To, so they can answer you directly. Sending does
**not** change the status — set that in the same form if the item is done.
If outgoing email is not set up the reply is saved but not sent, and the page
says so. A record whose reporter's login has since been deleted has no Send
reply button.

When a report arrives, every active **superuser** with an email address is
emailed (rota admins are not — they run the practice, not the code). With no
outgoing email configured the report still lands here; only the email is
skipped. One person can send at most ten reports an hour — and each report
is one email, so that is the ceiling on the inbox too.
