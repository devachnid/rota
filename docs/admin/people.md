# People

**Where:** sidebar › People › Clinicians / Clinician groups / Login accounts; Working patterns › Trainee profiles

## Clinician groups

`/admin/rota/cliniciangroup/` — the bands the practice is organised into:
Partner, Salaried, GPST, PA, Locum.

Groups do three jobs: they order the grid, they drive a staffing warning, and
they are a shorthand for "these people" when restricting a session type.

### Name

Shown as the section heading on the grid.

### Display order

**Default: 100.** Lower sorts first. The grid groups clinicians under their
group heading in this order. Leave gaps (100, 200, 300) so you can slot a new
group in without renumbering.

### Min per session

**Optional.** Warn when fewer than this many members of the group are in on a
session.

Blank means no warning for this group — which is the right setting for most.
Set it on the groups whose absence actually creates a problem: a Salaried
minimum of 3 produces "Salaried: 2/3 in (AM)" in the day header when only two
are in.

Counts anyone in the group with a **non-absence** entry that session, so a GP on
annual leave correctly does not count as present. It does not care what they are
doing otherwise — admin time counts as being in the building.

### Is locum group

Marks the group as locums. Locums are shown in their own section at the bottom
of the grid with the "Need" row for
[locum requirements](day-to-day.md#locum-requirements) beneath them.

## Clinicians

`/admin/rota/clinician/`

### Name / Initials

Name appears in reports and dropdowns; **initials appear in the grid**, where
space is tight. Keep initials genuinely short and unambiguous — two clinicians
sharing initials is legal but will confuse whoever reads the rota.

### Group

Which band they belong to. Drives grid position, the group minimum warning, and
any session type restricted by `allowed_groups`.

### User

Links this clinician to a **login account**, so they can see My Schedule and
propose swaps. Optional: leave it blank for someone who is on the rota but
does not use the app — the rota still works, they simply cannot sign in.
Locums often sit like this. Create the account first — see [Login
accounts](#login-accounts) below.

### Active

**Untick instead of deleting.** An inactive clinician:

- disappears from every eligibility pool the fill engine uses
- keeps all their historical entries intact
- keeps their name on past reports

Deleting a clinician would take their history with them. There is no reason to
do it.

One subtlety: if a session type lists a clinician individually in
`allowed_clinicians` and that clinician goes inactive, the type stays
*restricted* — it does not silently fall open to everyone. A type whose only
named clinician has left is restricted to nobody until you fix it.

### Is trainer

**May supervise trainee mentoring sessions.**

The mentoring pass pairs each trainee with a trainer for one session a week. It
prefers the trainee's own named trainer and substitutes another trainer when
theirs is unavailable — so tick this on everyone who can legitimately supervise,
not only on the named trainers.

The trainer dropdown on a trainee profile only offers clinicians with this
ticked.

### Breathe employee

Which BreatheHR employee this clinician is. A dropdown of your Breathe
employees; pick one and save. **Unlinked clinicians have no leave read for
them and are treated as available** — the sync status page and the week grid
both warn admins about them. See [Leave from Breathe](breathe.md).

## Login accounts

`/admin/accounts/user/` — who can sign in, and how. A login account is
separate from a clinician; the clinician's [User](#user) field links the two.

The list shows each account's email, **Admin status**, **Active**, whether it
is **Set up** (has a password), and the linked clinician. Search by email;
filter by Admin status or Active.

### Adding someone

**Add login account** asks for two things: their email, and whether they are
an admin. There is no password to type. Saving sends an **invitation** — an
email with a link to choose their own password — and opens their page, which
reads *Invited 4 Sep, link expires 11 Sep* until they have, then *Set up*. A
link lasts seven days and works once; using it signs them straight in.

If outgoing email is not set up (the dashboard's *Outgoing email* step says
so), or the relay refuses, you are shown the link once instead, to copy into
an email yourself. Nobody — not even you — ever sees anyone's password.

### The State field and the send button

Every account's page carries a **State** — *Not yet invited*; *Invited …,
link expires …*; *Invitation expired — send another*; *Set up*; or *Set up —
last link sent 4 Sep 14:02* — and one button in the save row, chosen by it:

- **Send invitation again** while they have no password yet — for a link
  that expired or never arrived.
- **Send password-reset link** once they have one — for someone who has
  forgotten it. They can also do this themselves with *Forgotten your
  password?* on the login page, which works for an unfinished invitation too;
  the same account is not sent a second link within five minutes.

Pressing either saves the page and sends. To invite a whole practice at
once, tick the accounts on the list and choose **Send invitation or reset
link**; each account gets whichever it needs.

### Admin status

Tick **Admin status** on anyone who should run fills, publish weeks and
approve requests; it is also what lets them into this admin. There is no
separate staff flag to set — Django's `is_staff` follows Admin status.

An admin cannot see a **superuser's** account in the list, open it, or grant
superuser to anyone. Only a superuser sees the System fieldset (Active,
Superuser status), the System group in the sidebar, and the password field
with its direct set-password form — an emergency tool that nothing links to.

### Deactivating

Untick **Active** rather than deleting. An inactive account cannot sign in by
password or passkey, its links are refused, and its history stays.

### Passkeys

A person adds passkeys to their own account from **Account** (their email in
the app's header): their phone's Face ID or fingerprint, a laptop's Windows
Hello or Touch ID, or a password manager. That page lists each passkey with
when it was added and last used, and lets them remove one. Their password
still works, and is how they get back in if a device is lost.

You cannot add one for them — only the device that holds the key can — but
you can revoke one: open their login account, and under **Passkeys** each row
shows the name, the authenticator, and when it was added and last used; tick
*Delete* on the lost device's row and save. Passkeys are bound to this site's
address; if the rota ever moves to a different domain, everyone enrols again.

Passkeys are for personal devices. Do not enrol one on a shared surgery PC:
the login page offers every passkey enrolled on that machine to whoever
clicks the email field, and where colleagues share a Windows login they
share its PIN too, so the passkey would let any of them in.

### Signing in and lockouts

People sign in with their email and password, or with a passkey. On the login
page a passkey enrolled on that device is offered in the email field's
autofill where the browser supports it, and **Sign in with a passkey** is
the explicit button. After a password sign-in on a device with no passkey, a
one-time card offers to add one; *Not now* puts it away for thirty days on
that browser.

Five wrong passwords within an hour — counted against the email *and*
against the address they came from — lock that email and that address out of
password sign-in for an hour. Any successful login from an address clears its
counter, so one colleague's mistakes on the surgery's shared connection do
not lock the building out. A passkey still signs in during a lockout: it
proves possession of the device, which is the stronger claim; a forged
assertion for a registered passkey counts like a wrong password.

Superusers can see the record under the **System** group: **Access
failures** is the permanent log of every failed attempt; **Access attempts**
is the live counter, empty for an address as soon as someone there has logged
in; **Access logs** records successful sign-ins.

## Trainee profile

Edited **inline on the Clinician admin page**, not as a separate menu item.
Create one for each trainee.

### Stage

FY2, ST1, ST2 or ST3. Selects which [trainee stage
rule](coverage-rules.md#trainee-stage-rules) supplies their weekly VTS, SDL and
mentoring rates.

### WTE percent

**Default: 100.** Scales all three weekly rates. A 60% ST3 with a stage rule of
1 VTS per week accrues 0.6 VTS per week, which the engine turns into whole
sessions as the weeks accumulate rather than trying to place a fraction.

### Trainer

The trainee's named trainer for the placement. Only clinicians with
[is trainer](#is-trainer) ticked are offered.

**Optional.** Leave it blank if you want the engine to pick any available
trainer each week rather than preferring one.

### Placement start / Placement end

The placement window. The trainee only appears in the trainee report and only
receives trainee sessions while today falls inside it, so an expired placement
tidies itself out of the way.

### Requirements tracked from

**The field that most often needs setting, and is easy to miss.**

Blank means requirements accrue from `placement_start`. For a placement that
began before you started using this app, that makes the engine treat every week
since then as owed — and the trainee shows a large phantom backlog they can
never clear.

Set this to the date the rota system actually started tracking them. Accrual
then anchors here instead, and the trainee report's "expected" column counts
from this date. That is deliberate: the app reports what it was asked to track,
not the placement's full contractual total.
