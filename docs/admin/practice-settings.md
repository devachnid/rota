# Practice settings and sites

## Practice settings

`/admin/rota/practicesettings/` — a **single row**. The admin refuses to create
a second one, because the whole app loads settings by convention from the one
record. If you see an "Add" button do nothing, that is why.

### Minimum clinical per session

**Default: 2.** The number of clinical GPs the practice considers the floor for
a single session.

Purely a **warning threshold** — it does not make the fill engine place anyone.
Any session with fewer than this many entries of a *clinical* session type gets
a red "Only N clinical GP(s)" strip in that day's grid header. Absence and
non-clinical sessions do not count toward it.

Set it to what makes you want to act, not to what you would like. A threshold
that fires every day gets ignored.

### Leave year start month / Leave year start day

**Default: 1 April.** Defines the window every leave balance is measured over.
"Taken", "booked" and "remaining" on the leave report and on a GP's My Schedule
all count only entries falling inside the current leave year.

The year runs from this month/day to the day before the same date next year. If
today is before this year's start date, the app rolls back to last year's — so
the window is always the one you are currently in.

**29 February is handled.** If you set 29 as the day, the app clamps to the last
day of that month in non-leap years rather than crashing or skipping. An admin
who configures 29 February is taken to mean "end of February".

### Default fill session type

The session type used by assisted fill's **"Fill remaining empty cells"**
checkbox — usually Routine.

This is the only thing that box does: after every other pass has run, any
clinician who works a session and is still free gets this type. Leave it blank
and ticking the box does nothing at all, silently.

The type's own eligibility restrictions still apply, so a default type with
`allowed_groups` set will only be given to those groups.

### Open weekdays

**Default: `0,1,2,3,4`** — Monday to Friday. Comma-separated, **Monday = 0**.

Days outside this list are not filled, not warned about, and are treated as
closed everywhere. Add `5` for Saturday if you run weekend sessions.

This is the practice's normal working week. One-off closures are
[closed days](availability.md#closed-days) instead.

### VTS / SDL / Mentoring session type

Point each at the session type that represents that activity. They are what
connects the trainee stage rules to real sessions on the grid.

**Leaving one blank skips that trainee pass entirely — no error, no warning.**
If trainees are getting no VTS, this is the first thing to check.

Create them as **Non-clinical** category types, so they do not count toward the
minimum-clinical-GPs warning. A trainee doing SDL is not clinical cover.

## Sites

`/admin/rota/site/` — just a name. Used for branch surgeries.

A site can be stamped on a rota entry in three ways, in this order of
precedence: whatever an admin picks by hand on the cell, then a recurring
commitment's own site, then the session type's `default_site`.

If you have one branch surgery, create it here and set it as `default_site` on
the session types that happen there — that way the fill engine stamps it
automatically and the grid shows where people are without anyone typing it.

Sites are display and record-keeping only. Nothing in the fill engine treats
two sites as mutually exclusive; a clinician placed at a branch site is simply
busy for that session like any other.
