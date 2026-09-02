# Leave from Breathe

Leave is not requested or approved in the rota. It is managed in BreatheHR and
read from there — read-only, every fifteen minutes — so that the grid shows who
is off and assisted fill never assigns them.

## Setting it up, in this order

1. **Put the key in the environment.** Add to `/etc/rota.env`:
   ```
   BREATHE_API_KEY=…
   BREATHE_API_URL=https://api.breathehr.com/v1
   ```
   and restart gunicorn. The key never goes in a file in the repository.
2. **Migrate.** `python manage.py migrate`.
3. **Link every clinician.** `/admin/rota/clinician/` — each clinician's
   **Breathe employee** field is a dropdown of your Breathe employees. Pick the
   right one and save. Where a clinician's login email matches a Breathe
   employee's email, that person is pre-selected; you still have to save.
4. **Run the first sync.** `/admin/rota/breathesyncrun/` → **Refresh now**, or
   `python manage.py breathe_sync`. Add `--dry-run` to fetch and count without
   writing, to check a real account's shape first.
5. **Enable the timer.** `systemctl enable --now rota-breathe.timer`.

Step 3 before step 4 matters: a sync before anyone is linked reads everything
and stores nothing, reporting every record as "for unlinked employees".

## What counts as off

Three Breathe sources, combined and de-duplicated:

- **Approved leave requests** — holiday, and other leave (maternity, paternity, …).
- **Absences** logged directly by HR.
- **Sickness.** Shown as its own chip. The sickness *type* is never read into
  the rota — only that the person is off.

**Pending requests are not shown.** Leave appears on the rota when Breathe says
it is approved, within fifteen minutes.

**A week already published keeps its sessions.** Nothing in the rota overwrites
a session when leave is approved in Breathe afterwards, so the week grid warns
admins — "1 rostered on Breathe leave (AM)" on that day's header — and you clear
the session by hand.

## Breathe leave mapping

`/admin/rota/breatheleavemapping/` — how each kind of Breathe record renders.
Holiday → **AL**, sickness → **SICK**, other leave → **OTH** by default; add a
row with a reason name — "Maternity" → MAT — to give a specific reason its own
chip. A reason with no row uses its kind's default.

Every kind's default row (the one with a blank reason) is seeded by migration
and cannot be deleted from the admin — deleting it would make every absence of
that kind with no more specific mapping render as an empty cell, silently. A
reason-specific row stays deletable; it only narrows a kind's default, it is
not it. The [sync status page](#the-sync-status-page) below counts absences
this has already happened to.

## The sync status page

`/admin/rota/breathesyncrun/` shows the last successful sync and its counts, the
most recent error if a run failed, how many stored absences currently have no
mapping and render as empty cells, and **every clinician not linked to
Breathe**. Unlinked clinicians have no leave read for them and are treated as
available; the week grid warns admins about them too.

**Refresh now** runs a sync immediately — useful the moment leave has just been
approved in Breathe and you want to fill the gap. It refuses if a sync ran in
the last minute, and is disabled altogether until `BREATHE_API_KEY` is set.

## If Breathe is down

The rota keeps working from the last successful sync. Nothing blocks on
Breathe. The status page shows the error; the next timer run tries again.

## Breathe absence

`/admin/rota/breatheabsence/` — the rows the sync wrote, read-only. Useful to
check what Breathe actually said about someone. Edit leave in Breathe, not here.
