# Time off from FindMyShift

**Date:** 2026-10-23
**Status:** Built (PR #57)
**Replaces:** `2026-09-02-breathe-leave-design.md`. The Breathe integration is
deleted, not kept beside this.

## Purpose

The practice manages time off in FindMyShift. The rota reads it from there —
read-only, every fifteen minutes — into the same overlay the Breathe sync
filled, so that everything downstream (the availability resolver, chips, the
clash ring, the swap check, the day view and My Schedule) is unchanged in kind.

## What FindMyShift gives us

From the developer portal (`findmyshift.co.uk/developers`, API 1.4):

- Every method takes GET or POST; the key is a parameter named `apiKey`
  (query string, form field or header). We POST it as a form field so it is
  never in a URL.
- `teams/list`; `staff/list` (optional `teamId`; all teams without it);
  `time-off/list` (`teamId`, optional `staffId`, `from`, `to`).
- One request at a time per key; 429 over that. No pagination documented.
- **No response shapes are documented** — not field names, not the date
  format, not whether a list comes bare or wrapped. An unauthenticated call
  answers with a plain-text `401: No authentication parameters found…`, so
  errors are text, not JSON.
- **Measured on a test account (2026-10-23):** lists come as bare JSON
  arrays; a team is `{teamId, title, timeZone, timeOffTypes: [{timeOffTypeId,
  description, deleted, …}], …}`; a staff record is `{staffId, firstName,
  lastName, displayName, emailAddress, dateStarted, dateFinished, active,
  payrollId, …}` plus pay rates, salaries, date of birth and phone numbers,
  which the client drops at parse; date/times are ISO 8601 in UTC
  (`2026-10-23T14:20:21.297Z`), dates are `yyyy-MM-dd`; a bad parameter is a
  plain-text `400: Parameter not found or not valid: teamId`; API access is a
  feature of the account's plan (`401: Your subscriptions do not include API
  access`). A time-off record, measured the same day once the account held
  some, is day-based: `timeOffId`, `staffId` (null when assigned to no one),
  `timeOffTypeId` and `type` (the type's name), `firstDayOff`/`lastDayOff`
  as dates, `days` (the weekdays it applies to, Sunday 0), `dateRequested`,
  `dateApproved` (null while pending), `dateDeleted` (set on a deleted
  record, which still comes back), `managerNotes`, pay and allowance fields,
  and `recurrence`/`recurrenceInterval`/`recursUntil`. **No clock times.**
  FindMyShift's guide gives the convention for part of a day: book the whole
  date and describe it "Morning off" or "Afternoon off" (and, if tracked,
  set the allowance used to 0.5).

## Design

### Reading what nobody documented

`services/findmyshift/sync.FIELDS` names, for each thing the sync needs
(id, staff, start, end, approved, deleted, reason), the keys it may come
under, tried in order; a dotted name reads a nested object. `client.rows()`
accepts a bare array, an array under any of a few known keys, or an object
holding exactly one list. `parse_when()` reads ISO 8601 with or without a
time, with a space or a T, with or without an offset, and the .NET
`/Date(ms)/` form; a value carrying an offset is moved to `TIME_ZONE`.

A record missing a field it must have fails the run with a message naming
the record id and the keys it carried — never a value — and
`findmyshift_sync --inspect` prints the same for a whole account: counts,
which key each field was read from, the reasons in use. That is step 4 of
the admin guide, before the first real sync. The fixtures in
`tests/fixtures/findmyshift/` are synthetic and are the shape the sync
*reads*; if a real account differs, the fix is a name in `FIELDS`.

### Days, weekday masks, and (if ever sent) times

A measured record is whole days: `firstDayOff` to `lastDayOff`, with `days`
naming the weekdays inside that range the time off applies to. The sync
splits the range into runs of applicable days (`sync.day_runs`), each a
span of its own, so an unticked Wednesday is a working day. A record
assigned to no one is skipped; a recurring record is read as its first
occurrence and logged, since the rule's shape is unmeasured. A single-day
record whose `description` says "morning"/"AM" or "afternoon"/"PM"
(`sync.half_day`) is that half only; the description is read for that
phrase and never stored.

Should a record ever carry clock times (the pre-measurement guess, kept as
a fallback), `spans.Span.from_times` turns the pair into the overlay's
existing shape (date range plus half-day flags), so the resolver's
`parts_off` is untouched:

| start                  | first day      |
|------------------------|----------------|
| no time, or < midday   | whole day      |
| ≥ midday               | PM only        |

| end                                | last day        |
|------------------------------------|-----------------|
| no time, or > midday               | whole day       |
| 00:00 < t ≤ midday                 | AM only         |
| 00:00 on a later day than start    | the day before, whole |

Midday is `FINDMYSHIFT_MIDDAY`, default 13:00. A boundary time the rota
cannot express (09:00–17:00) is the whole day: off is the safer reading.

### Reasons, not kinds

Breathe had three kinds and a free-text reason on one of them. FindMyShift
has a *reason* — the category the practice set up (Holiday, Sick, Unpaid…) —
and a free-text *comment*. The mapping (`TimeOffMapping`) is keyed on the
reason text, with a blank-reason default row; the migration seeds the
default → OTH and the common names onto AL and SICK. The status page names
reasons seen with no row of their own. The comment is never read: it is
where someone writes what they were ill with.

### Who is linked

`Clinician.findmyshift_staff_id` (text; FindMyShift's ids are documented as
text), unique and nullable, chosen from a cached `staff/list` projected to
name, email, payroll id, finished date and team. The email match pre-selects
a staff member on an unlinked clinician's form. Locums are left out of every
"not linked" count, as before: they book their own sessions.

### What is removed

`BreatheAbsence`, `BreatheLeaveMapping`, `BreatheSyncRun`,
`Clinician.breathe_employee_id`, `services/breathe/`, `breathe_sync`,
`rota-breathe.*`, the Breathe admin pages and `docs/admin/breathe.md`.
Migration `0034_findmyshift` drops the tables whole (nothing carries over;
the overlay is rebuilt by the first sync) and re-creates the mapping seed.
`tests/test_findmyshift_deploy.py` asserts nothing deployable still says
"Breathe".

### Operations

Settings: `FINDMYSHIFT_API_KEY`, `FINDMYSHIFT_API_URL`,
`FINDMYSHIFT_TEAM_ID` (blank = every team the key sees),
`FINDMYSHIFT_MIDDAY`. `rota.E007` flags a non-https URL. The timer is
`rota-findmyshift.timer`; the Breathe units must be disabled and removed by
hand on a box that ran them (admin guide, *Moving from Breathe*).

## Not done, on purpose

- No OAuth: the key is for the practice's own account, which is exactly
  the case the portal says a key is for.
- No `reports/time-off`; `time-off/list` is the record-level source.
- No write-back of anything to FindMyShift.
- Shifts in FindMyShift are not read. The rota remains the rota.
