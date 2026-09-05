# Swaps that apply, and tell people — design

**Date:** 2026-09-05. **Status:** agreed in chat with Tom; built as two PRs.

## Why

Testing on staging showed three things about swap requests:

1. A GP proposing to cover a colleague's session (and be covered in return)
   could not be applied. The app only knew one kind of swap — both GPs work
   both sessions and trade what they do in them — and refused the other.
2. The admin's *Swap requests* screen exposed **Status** as an editable
   dropdown. Setting it to *Applied* relabelled the row without touching the
   rota, writing an audit row or stamping the decision.
3. Nobody is told anything. The colleague is not emailed when asked; the
   admin is not told when a swap awaits approval; the proposer is not told
   the outcome. The only trace is a card on My schedule, which the login
   landing page does not point at.

## PR 1 — swaps apply correctly

### Two kinds, chosen from the rota

Given the proposer's session and the colleague's session (each expanded to
the whole day when it is half of a full duty day):

- **Work** — both GPs already have entries in every session involved. What
  each does in them is exchanged: session type, site, note and full-day
  grouping. The people stay where they are. The duty-swap case; unchanged.
- **People** — each GP has an entry only in their own session and none in
  the other's. The entries change hands: the proposer's becomes the
  colleague's and vice versa, each keeping what it is. Moved entries are
  marked manually set so assisted fill leaves them alone. The
  cover-for-each-other case; new.
- **Neither** — anything in between. Refused with one sentence naming the
  facts that break both patterns, followed by what the two patterns are.

Checks that apply to both kinds: each GP still has the session they put
forward; no paired session (mentoring, `companion_group`) is involved; and
neither GP is on Breathe leave for a session they would take on.

`rota.services.swaps` gains `WORK`, `PEOPLE`, `kind(req)`, `describe(req)`
(one sentence saying what applying would do) and `when(day, part)`
("Fri 11 Sep PM"). `validate(req)` keeps its signature and returns friendly
dates. `approve()` applies by kind.

### Checked at proposal time too

The propose form runs `validate()` on the unsaved request. Problems are shown
as form errors and nothing is created, so a colleague is never asked about a
swap that could not be applied. Approval validates again, since the rota may
have changed.

### The admin does the same thing as Requests

`SwapRequestAdmin`: everything read-only except **Admin comment**; a
**Checks** field showing the problems or the describe sentence; two
submit-line actions, **Approve and apply** (shown only while *Awaiting admin*)
and **Decline** (while *Awaiting colleague* or *Awaiting admin*), both calling
the service. No add. The Requests page shows the describe sentence above its
buttons.

## PR 2 — notifications

Same mail door as invitations and feedback (`accounts.mail.TRACKING_OFF`,
`email_is_configured()`, failures logged and never raised). Plain text. Every
message names both sessions using `describe()` and links to the page where
the reader acts.

| Event | To | Link |
|---|---|---|
| Proposed | colleague | My schedule (accept / decline) |
| Colleague accepted | proposer; every active rota admin with an email | proposer: My schedule; admins: Requests |
| Colleague declined | proposer | My schedule |
| Admin applied | both GPs | My schedule |
| Admin declined | both GPs, with the admin's comment | My schedule |

Sent from the views and admin actions after the service call succeeds, never
from the service. A GP with no linked account, or no email, is skipped
silently — the swap still happens.

### In the app

- Dashboard **Health**: *Swaps awaiting your approval* — count of *Awaiting
  admin*, linking to `/requests/`, level warn.
- A count on the **My schedule** nav link and phone tab when swaps await the
  signed-in GP's answer; a count on **Requests** (admins) when swaps await
  approval. One context processor, one cheap query per page for a signed-in
  user, none for anonymous.
- The colleague can add a comment when declining (`colleague_comment`, new
  field, migration). It is shown to the proposer on My schedule and in the
  declined email.

## Docs

Day-to-day swap section rewritten around the two kinds and the admin actions;
README's outgoing-email paragraph lists the swap emails; backlog Settled
entries for both PRs.
