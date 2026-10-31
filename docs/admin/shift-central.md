# Time off from Shift Central

**Where:** sidebar › Time off from Shift Central › Sync status / Reason mapping / Time off

Leave is not requested or approved in the rota. It is booked and approved in
Shift Central and read from there — read-only, every fifteen minutes — so that
the grid shows who is off and assisted fill never assigns them.

## Setting it up, in this order

1. **Make a token in Shift Central.** Add a long random string to
   `LEAVE_API_TOKENS` in Shift Central's environment and restart it. The
   token lets the rota read approved leave and nothing else. It never goes in
   a file in either repository.
2. **Put the address and the token in the rota's environment.** Add to
   `/etc/rota.env`:
   ```
   SHIFT_CENTRAL_URL=https://shifts.example.org
   SHIFT_CENTRAL_TOKEN=…
   ```
   The URL must be `https`: the token is never sent over anything else, even
   by a redirect, and `check --deploy` flags a plain-http URL (`rota.E007`). A
   token with a space or a line break in it is treated as not set, and the
   status page says so. Gunicorn is restarted in step 4, once the database has
   been migrated.
3. **Install the timer's units.** From `/srv/rota`, with this release pulled (`git pull`;
   a fresh install already has it):
   ```
   cp deploy/rota-shift-central.service deploy/rota-shift-central.timer /etc/systemd/system/
   systemctl daemon-reload
   ```
   Without this, step 8 has no timer to enable.
4. **Redeploy, then restart.** On a box that ran the old time-off reader,
   first disable its timer, as the section just after these steps says, so it
   cannot run against the migrated database. Then, as root, from
   `/srv/rota`, the README's *Redeploying* steps (`deploy/manage`, not plain
   `manage.py`; see the README's Deploy section for why). This release changes
   the rota's CSS, so `collectstatic` is not optional:
   ```
   .venv/bin/pip install -r requirements.txt
   deploy/manage migrate
   deploy/manage collectstatic --noinput
   deploy/manage check --deploy
   systemctl restart rota
   ```
5. **Give every clinician a login whose email matches Shift Central's.**
   `/admin/rota/clinician/` — each clinician's **login account** is the link.
   Shift Central names each person's leave by their email address, and the rota
   matches it to the clinician whose login has that address (case does not
   matter). Locums are left out: a locum books their own sessions and has no
   leave to read. The status page lists every other clinician who still has no
   login email.
6. **Map the leave types.** `/admin/rota/timeoffmapping/` — see [Reason
   mapping](#reason-mapping). A reason is the name of a Shift Central leave
   type (Holiday, Sick leave, TOIL, Training, …).
7. **Run the first sync.** `/admin/rota/timeoffsyncrun/status/` → **Refresh
   now**, or `deploy/manage shift_central_sync`. Add `--dry-run` to fetch and
   count without writing.
8. **Enable the timer.** `systemctl enable --now rota-shift-central.timer`.

Step 5 before step 7 matters: a sync before anyone has an email reads
everything and stores nothing, reporting every address as unmatched.

### Moving from FindMyShift

The FindMyShift reader is gone. On a box that ran it:

```
systemctl disable --now rota-findmyshift.timer
rm /etc/systemd/system/rota-findmyshift.service /etc/systemd/system/rota-findmyshift.timer
systemctl daemon-reload
```

Remove the `FINDMYSHIFT_*` lines from `/etc/rota.env` (they are ignored, but a
key that no longer does anything should not sit in a file). Migration `0035`
drops the clinicians' staff links; nothing needs linking again beyond giving
each clinician a login email, as in step 5 above.

## What counts as off

Every approved leave booking Shift Central returns (one awaiting cancellation
still counts until it is cancelled), for every clinician whose login email
matches, in a window from a year ago to two years ahead.

**Pending and declined requests are not shown.** Leave appears on the rota when
Shift Central says it is approved, within fifteen minutes. A booking cancelled
there disappears at the next sync: each run replaces the whole set.

**Whole days.** A booking is a first and a last day. Every day in the range is
off, both halves.

**A morning or an afternoon.** A booking for part of one day comes through as
that half, and the rota treats it as a half day: a morning off ends at midday,
an afternoon off starts there. A booking with clock times (an appointment, say)
is read as the half it falls in: one that ends by 13:00 is a morning off, one
that starts at or after 13:00 is an afternoon off, and one that straddles
midday is the whole day.

**A week already published keeps its sessions.** Nothing in the rota
overwrites a session when leave is approved afterwards. Instead the cell is
ringed in red, its tooltip says "On leave (Shift Central): Holiday", and the
day's header names who — "On leave (Shift Central) but rostered (AM): TH
(Holiday)". The ring and tooltip are visible to everyone who can see the
session; the header line is for admins, who clear the session by hand. On the
day view and on My Schedule the clinician files under "On leave", with the
ringed session still shown.

Every chip's tooltip names the reason — "Holiday — from Shift Central", "Sick
leave — from Shift Central", "Training — from Shift Central". The reason is the
leave type's name in Shift Central; a booking with none reads "Time off". The
free-text description of a booking is never read: that is where someone writes
why they are off sick.

## Reason mapping

`/admin/rota/timeoffmapping/` — how each Shift Central leave type renders. A
row per type, named exactly as Shift Central names it, onto an absence-category
session type; the row with a blank reason is the default for any type with no
row of its own. The migration seeds the default → **OTH**, *Holiday*, *Annual
leave* and *Bank holiday* → **AL**, *Sick*, *Sickness* and *Sick leave* →
**SICK**, and *TOIL* and *Training* → **OTH**. Add a row for each leave type
your Shift Central actually uses — "Maternity" → MAT, say — and the [sync
status page](#the-sync-status-page) names the reasons it has seen that still
have none.

The default row cannot be deleted from the admin — deleting it would make
every absence with no row of its own render as an empty cell, silently. A
reason-specific row stays deletable; it only narrows the default, it is not it.

## The sync status page

`/admin/rota/timeoffsyncrun/status/` shows whether Shift Central is configured,
the last successful sync and its counts — records read, clinicians matched,
emails unmatched, records outside the window (each run is also a
**Shift Central sync run** row, at `/admin/rota/timeoffsyncrun/`) — the most recent error if a
run failed, and the lists that need action:

- **Unmatched emails** — Shift Central has leave for these addresses but no
  active clinician's login has them. Either the login email differs from the
  one in Shift Central, or the person is not a clinician here.
- **Reasons with no mapping row of their own** — rendering as the default chip,
  or as empty cells if the default is gone.
- **Clinicians without a login email** — no leave can be matched for them, so
  they are treated as available; the week grid and the dashboard warn admins
  about them too. Locums are never counted.

**Refresh now** runs a sync immediately — useful the moment leave has just been
approved and you want to fill the gap. It refuses if a sync ran in the last
minute, and is disabled altogether until `SHIFT_CENTRAL_URL` and
`SHIFT_CENTRAL_TOKEN` are both set.

## If Shift Central is down

The rota keeps working from the last successful sync. Nothing blocks on Shift
Central. The status page shows the error; the next timer run tries again. A
refused token reads as a 401 or 403 on the status page: check the token against
`LEAVE_API_TOKENS` in Shift Central.

## Time off

`/admin/rota/timeoff/` — the rows the sync wrote, read-only. Useful to check
what Shift Central actually said about someone. Edit leave in Shift Central,
not here.
