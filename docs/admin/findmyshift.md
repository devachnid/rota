# Time off from FindMyShift

**Where:** sidebar › Time off from FindMyShift › Sync status / Reason mapping / Time off

Leave is not requested or approved in the rota. It is managed in FindMyShift
as *time off* and read from there — read-only, every fifteen minutes — so that
the grid shows who is off and assisted fill never assigns them.

## Setting it up, in this order

1. **Get an API key.** In FindMyShift, an account's API key is issued from the
   developer portal (`findmyshift.co.uk/developers`, *Getting started*). The
   key reads everything the account that issued it can see, so issue it from
   an account that can see the whole team's time off and nothing it does not
   need.
2. **Put the key in the environment.** Add to `/etc/rota.env`:
   ```
   FINDMYSHIFT_API_KEY=…
   FINDMYSHIFT_API_URL=https://www.findmyshift.co.uk/api/1.4
   FINDMYSHIFT_TEAM_ID=
   FINDMYSHIFT_MIDDAY=13:00
   ```
   and restart gunicorn. The key never goes in a file in the repository. The
   URL must be `https`: the key is never sent over anything else, even by a
   redirect, and `check --deploy` flags a plain-http URL (`rota.E007`). The
   team id can stay blank: the sync then reads every team the key can see,
   which for a practice with one team is the same thing. `FINDMYSHIFT_MIDDAY`
   is where the morning ends, for half days — see [What counts as
   off](#what-counts-as-off).
3. **Migrate.** `deploy/manage migrate`, as root, from `/srv/rota` (see the
   README's Deploy section for why not plain `manage.py`).
4. **Inspect the account.** `deploy/manage findmyshift_sync --inspect` prints
   what the account sends — the number of teams, staff and time-off records,
   the field each thing the sync needs was read from, and the reasons in use —
   and never a value from a record. FindMyShift documents its methods but not
   the shape of a response, so this is how to confirm the sync reads yours.
   A line reading `NOT FOUND` against `staff`, `start` or `end` means the
   account names a field differently; the sync will refuse to run until that
   name is added to `FIELDS` in `rota/services/findmyshift/sync.py`.
5. **Link every clinician except locums.** `/admin/rota/clinician/` — each
   clinician's **FindMyShift staff member** field is a dropdown of your staff.
   Pick the right one and save. Where a clinician's login email matches a
   staff member's email address, that person is pre-selected; you still have
   to save.
6. **Map the reasons.** `/admin/rota/timeoffmapping/` — see [Reason
   mapping](#reason-mapping). The inspect output lists the reasons in use.
7. **Run the first sync.** `/admin/rota/timeoffsyncrun/status/` → **Refresh
   now**, or `deploy/manage findmyshift_sync`. Add `--dry-run` to fetch and
   count without writing.
8. **Enable the timer.** `systemctl enable --now rota-findmyshift.timer`.

Step 5 before step 7 matters: a sync before anyone is linked reads everything
and stores nothing, reporting every record as "for unlinked staff".

### Moving from Breathe

The Breathe integration is gone. On a box that ran it:

```
systemctl disable --now rota-breathe.timer
rm /etc/systemd/system/rota-breathe.service /etc/systemd/system/rota-breathe.timer
systemctl daemon-reload
```

Remove `BREATHE_API_KEY` and `BREATHE_API_URL` from `/etc/rota.env` (they are
ignored, but a key that no longer does anything should not sit in a file).
Migration `0034_findmyshift` drops the Breathe tables and the clinicians'
Breathe links; every clinician has to be linked again, to their FindMyShift
staff member.

## What counts as off

Every approved time-off record FindMyShift returns, for every linked
clinician, in a window from a year ago to two years ahead.

**Pending requests are not shown.** Time off appears on the rota when
FindMyShift says it is approved, within fifteen minutes. A record FindMyShift
marks deleted is dropped. (An account whose records carry no approval field
at all is read as one where approval is not in use, and everything counts;
the inspect output says which.)

**Half days.** FindMyShift records a start and an end date/time; the rota's
unit is the morning or the afternoon. A record that starts at or after
`FINDMYSHIFT_MIDDAY` leaves the first morning working; one that ends at or
before it leaves the last afternoon working. Anything else on a boundary day
takes the whole day off — a record from 09:00 to 17:00 is not half a day the
rota can express, and off is the safer reading. An all-day record is read the
same whether FindMyShift ends it at 23:59 or at midnight the next day.

**A week already published keeps its sessions.** Nothing in the rota
overwrites a session when time off is approved in FindMyShift afterwards.
Instead the cell is ringed in red, its tooltip says "On FindMyShift leave:
Holiday", and the day's header names who — "On FindMyShift leave but
rostered (AM): TH (Holiday)". The ring and tooltip are visible to everyone
who can see the session; the header line is for admins, who clear the session
by hand. On the day view and on My Schedule the clinician files under "On
leave", with the ringed session still shown.

Every chip's tooltip names the reason — "Holiday — from FindMyShift", "Sick —
from FindMyShift", "Jury service — from FindMyShift". The reason is whatever
the practice set up in FindMyShift; a record with none reads "Time off". The
free-text comment on a record is never read into the rota: it is where someone
writes why they are off sick.

## Reason mapping

`/admin/rota/timeoffmapping/` — how each FindMyShift reason renders. A row per
reason, named exactly as FindMyShift names it, onto an absence-category
session type; the row with a blank reason is the default for any reason with
no row of its own. Migration `0034_findmyshift` seeds the default → **OTH**,
*Holiday* and *Annual leave* → **AL**, and *Sick*, *Sickness* and *Sick leave*
→ **SICK**. Add a row for each reason your account actually uses —
"Maternity" → MAT, say — and the [sync status page](#the-sync-status-page)
names the reasons it has seen that still have none.

The default row cannot be deleted from the admin — deleting it would make
every absence with no row of its own render as an empty cell, silently. A
reason-specific row stays deletable; it only narrows the default, it is not it.

## The sync status page

`/admin/rota/timeoffsyncrun/status/` shows the last successful sync and its
counts (each run is also a **FindMyShift sync run** row, at
`/admin/rota/timeoffsyncrun/`), the most recent error if a run failed, the reasons in the overlay
that have no mapping row of their own (rendering as the default chip, or as
empty cells if the default is gone), and **every clinician not linked to
FindMyShift**. Unlinked clinicians have no time off read for them and are
treated as available; the week grid and the dashboard warn admins about them
too. Locums are never counted: a locum books their own sessions and has no
time off to read, so their FindMyShift field stays blank.

**Refresh now** runs a sync immediately — useful the moment time off has just
been approved in FindMyShift and you want to fill the gap. It refuses if a
sync ran in the last minute, and is disabled altogether until
`FINDMYSHIFT_API_KEY` is set.

## If FindMyShift is down

The rota keeps working from the last successful sync. Nothing blocks on
FindMyShift. The status page shows the error; the next timer run tries again.
FindMyShift allows one request at a time per key and answers 429 over that;
the sync is sequential and never retries, so a 429 means something else is
using the same key.

## Time off

`/admin/rota/timeoff/` — the rows the sync wrote, read-only. Useful to check
what FindMyShift actually said about someone, including which record ids a
row came from. Edit time off in FindMyShift, not here.
