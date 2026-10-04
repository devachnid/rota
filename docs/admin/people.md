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

### Display order

**Default: 100.** Lower sorts first, within the group; ties are
alphabetical by name. The grid and the day view follow it. Dropdowns and
reports stay alphabetical, because a list you scan for a name should be
in name order. The admin's own clinician dropdowns (a rota entry's
clinician, a trainee's trainer) follow it too, since an admin set it.
Edit it inline on the clinician list — leave gaps (10, 20,
30) so someone new can be slotted in without renumbering.

### User

Links this clinician to a **login account**, so they can see My Schedule,
propose swaps and be asked for one — a colleague with no account is left out of
the swap form's colleague list, because the colleague has to accept. Optional:
leave it blank for someone who is on the rota but does not use the app — the
rota still works, they simply cannot sign in.
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
both warn admins about them. Leave it blank for a locum: Breathe holds
employees, not contractors, so locums are left out of that warning and the
list shows "locum — not on Breathe" for them. See [Leave from
Breathe](breathe.md).

## Login accounts

`/admin/accounts/user/` — who can sign in, and how. A login account is
separate from a clinician; the clinician's [User](#user) field links the two.

The list shows each account's email, **Admin status**, **Active**, whether it
is **Set up?** (has a password), and the linked clinician. Search by email;
filter by Admin status or Active.

**With the practice account on** (`PRACTICE_HR_URL`, see [Signing in with
the practice account](sign-in.md)), everyone signs in through the HR system
and much of what follows waits until it is turned off: there are no rota
passwords, so adding an account sends no invitation and reset links do
nothing; passkeys are retired; and **Admin status** is set on the HR system
— **Admin of rota**, under **Apps** on the person's login there — and is
read-only here, updated at each sign-in. An account is made for a new person
at their first sign-in, so there is no need to add one here first. Linking a
clinician, **Active** and the rest of the account's page work as below.

### Adding someone

**Add login account** asks for two things: their email, and whether they are
an admin. There is no password to type. Saving sends an **invitation** — an
email with a link to choose their own password — and opens their page, which
reads *Invited 4 Sep, link expires 11 Sep* until they have, then *Set up —
last link sent 4 Sep 14:02*. A link lasts seven days and works once; using it
signs them straight in.

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
With the practice account on it is not ticked here: it reads *Set on the HR
system: Login accounts › Apps › Admin of rota. It is updated at each
sign-in.*, and the add form leaves it out.

An admin cannot see a **superuser's** account in the list, open it, or grant
superuser to anyone. Only a superuser sees the System fieldset (Active,
Superuser status) and the System group in the sidebar, and only a superuser
can reach the direct set-password form at
`/admin/accounts/user/<id>/password/` — by URL alone, an emergency tool that
nothing links to.

### Deactivating

Untick **Active**. An inactive account cannot sign in by password or passkey,
its links are refused, and its history stays. Only a superuser can delete a
login outright. Deleting one would also take Django's record of any admin
changes that person made.

### Passkeys

A person adds passkeys to their own account from **Account** (in the menu
under their name, top right of the app's header): their phone's Face ID or fingerprint, a laptop's Windows
Hello or Touch ID, or a password manager. That page lists each passkey with
when it was added and last used, and lets them remove one. Their password
still works, and is how they get back in if a device is lost.

Adding a passkey asks for the password again unless they signed in within
the last ten minutes. A passkey keeps working after a password change, so
someone who finds a computer left signed in must not be able to add one of
their own. The owner is emailed each time one is added. If a passkey appears
that they didn't add, they reset their password from **Forgotten your
password?** and tick **Also remove all my passkeys**. That form offers the box
whenever the account has any passkeys.

You cannot add one for them — only the device that holds the key can — but
you can revoke one: open their login account, and under **Passkeys** each row
shows its name, the authenticator's id (its AAGUID), and when it was added and
last used; use the row's delete control on the lost device's row and save. Passkeys are bound to this site's
address; if the rota ever moves to a different domain, everyone enrols again.

Passkeys are for personal devices. Do not enrol one on a shared surgery PC:
the login page offers every passkey enrolled on that machine to whoever
clicks the email field, and where colleagues share a Windows login they
share its PIN too, so the passkey would let any of them in.

### Signing in and lockouts

People sign in with their email and password, or with a passkey. The email
is matched whatever its case — "Tom.Hodges@…" and "tom.hodges@…" are the
same account, and the add form refuses a second account that differs from
an existing one only by case. On the login
page a passkey enrolled on that device is offered in the email field's
autofill where the browser supports it, and **Sign in with a passkey** is
the explicit button. In a browser that has never enrolled or used a passkey,
the first pages after signing in carry a card offering to add one, until they
do or press *Not now*, which puts it away for thirty days in that browser.

Five wrong passwords within an hour lock that email out of password
sign-in for an hour, wherever they come from. An address is locked too, once
five *different* emails have wrong passwords outstanding from it. That is the
pattern of someone trying many accounts. The surgery's shared connection is
safe: one colleague's fumbles count once there, and each person's own
successful login clears their own count.

The hour runs from the lockout. Trying again while locked doesn't restart it,
so nobody can keep a colleague out by retrying. The locked-out page
offers the two ways in that still work. A passkey still signs in during a
lockout, because it proves possession of the device, which is the stronger
claim; a forged assertion for a registered passkey counts like a wrong
password. And a password link by email still works: setting a new password
signs them in.

Superusers can see the record under the **System** group:
- **Access failures** is the log of failed attempts, kept to the last
  thousand per email.
- **Access attempts** is the live counter. It is cleared for an email when
  that person next signs in.
- **Access logs** records successful sign-ins.

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
