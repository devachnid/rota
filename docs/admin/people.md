# People

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

Links this clinician to a **login account**, so they can see My Schedule,
request leave and propose swaps.

Optional. Leave it blank for someone who is on the rota but does not use the
app — the rota still works, they simply cannot log in. Locums often sit like
this.

Create the account first at `/admin/accounts/user/`. Tick **is rota admin** on
anyone who should be able to run fills, publish weeks and approve requests.
(`is staff` is separate and controls access to `/admin/` itself.)

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
