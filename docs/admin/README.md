# Admin guide

Reference for everything configurable at `/admin/`. One page per area, every
field explained — what it does, what depends on it, and what goes wrong if it
is set incorrectly.

The admin now explains itself: every field carries a sentence, every page a
short description, and the dashboard's Setup card walks a new practice
through the nine steps in order. This guide is the reference for the
"why" — read it when a setting does not do what you expected.

The `README.md` in the project root has the *sequence* for a first-time setup.
This is the *reference* for what each setting means once you are in there.

| Page | Covers |
|---|---|
| [Practice settings](practice-settings.md) | The practice-wide singleton, sites |
| [People](people.md) | Clinician groups, clinicians, login accounts (invitations, passkeys, lockouts), trainee profiles |
| [Availability](availability.md) | Pattern slots and the bulk editor, recurring commitments, closed days |
| [Session types](session-types.md) | Every flag on a session type, and what each one drives |
| [Coverage rules](coverage-rules.md) | The rules that tell the fill engine what must be staffed, plus trainee stage rules |
| [Day to day](day-to-day.md) | Assisted fill, rota entries, day notes, locums, leave, swaps, the audit log, feedback |
| [Leave from Breathe](breathe.md) | Linking clinicians, the sync, what counts as off |
| [Upgrading unfold](upgrading-unfold.md) | How to upgrade the admin package and what to test |

## The mental model

Five ideas explain most of the app.

**A session is half a day.** Everything is AM or PM. A "full day" is two
sessions, and a rule that says "one Duty per day" means two sessions of Duty.
Fairness and trainee requirements are counted in sessions, never in days.

**Availability and assignment are separate.** A **pattern slot** says a
clinician *works* Tuesday PM. A **rota entry** says what they are *doing* that
Tuesday PM. The fill engine can only assign someone to a session they work, so
a missing pattern is invisible until the fill quietly has nobody to place —
the single most common cause of "assisted fill did nothing".

**Draft and published are different states.** The fill engine creates drafts.
Only admins see them; GPs see nothing until a week is published. Re-running a
fill deletes and recreates its own drafts, and never touches a published entry
or one an admin set by hand.

**The fill engine runs in a fixed order,** and earlier passes win because later
ones can only use sessions still free:

1. **Recurring commitments** — personal fixtures, never overwritten
2. **Trainee VTS** — anchored to a fixed weekday/part where the stage rule sets one
3. **Coverage rules** — in `priority` order, lowest number first
4. **Mentoring** — pairs a trainee with a trainer
5. **Trainee SDL** — placed where it does least damage
6. **Default fill** — optional, only if you tick the box

If two rules compete for the same person, the one that runs earlier gets them.
For coverage rules specifically, `priority` decides.

**Nothing is deleted.** Deactivate a clinician rather than deleting them;
their history stays intact and they drop out of every eligibility pool.

## Where to start when something looks wrong

| Symptom | Look at |
|---|---|
| Assisted fill created nothing | [Pattern slots](availability.md#pattern-slots) — does anyone work those sessions? |
| "No eligible clinician" | [Session type restrictions](session-types.md#allowed-clinicians-and-allowed-groups) |
| A rule never places anything | [Coverage rule frequency and count](coverage-rules.md) — and check `priority` against competing rules |
| A trainee shows a huge backlog | [`requirements_tracked_from`](people.md#trainee-profile) |
| A warning you do not want | [Warnings](day-to-day.md#warnings-on-the-grid) — they come from three separate sources |
| Someone's leave is not on the grid | Are they [linked to Breathe](breathe.md#setting-it-up-in-this-order)? Has a sync run since it was approved? |
| Someone cannot sign in | [Login accounts](people.md#signing-in-and-lockouts) — an invitation link lasts seven days; a lockout lasts an hour and a passkey bypasses it |
| An invitation never arrived | Is [outgoing email](../../README.md#outgoing-email) set up? If not, each send shows the link once, to copy; **Send invitation again** mints a fresh one |
