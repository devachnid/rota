# Leave from BreatheHR

**Date:** 2026-09-02
**Status:** Approved design, pre-implementation
**Builds on:** the availability consolidation in `2026-08-30-rota-fixes-design.md`
and the `cell_state` extraction in `2026-08-31-frontend-phase2-design.md`, both
merged.

## Purpose

The practice manages leave in BreatheHR. This app stops managing it — no
requests, no approvals, no balances — and instead reads leave from Breathe's API
so that the rota shows who is off and the fill engine never assigns them. The
integration is read-only. Swaps are unaffected.

There is no live data yet, so this replaces the existing leave features outright
rather than migrating anything.

## What the API is, as measured

Everything below was verified against the test account, not read from
documentation — the documentation site renders client-side and is empty to a
fetcher. The facts that shaped the design:

- **Auth** is an `X-API-KEY` header. **Pagination** is a `Link` header with
  `rel="next"` and `rel="last"`, plus `total` and `per-page` headers; `per_page`
  caps at 100. **Rate limit**: 60 requests per 60 seconds per customer, returning
  429. **No webhooks.**
- Leave lives in **three endpoints** that overlap without agreeing. In the test
  account `/leave_requests` holds 11 approved requests across six employees;
  `/absences` holds two, both for one employee, and those two also appear in
  `/leave_requests` field-for-field under different ids with no cross-reference.
  `/sicknesses` is separate again. Whether the real account behaves the same is
  unknown, so the design unions all three and deduplicates by content.
- **Date filters differ between endpoints.** `/absences?start_date&end_date`
  returns records that *overlap* the window. `/leave_requests` with the same
  parameters returns records whose *start date* falls in a half-open window — a
  three-week leave starting 14 September is invisible to an October query. The
  sync therefore fetches everything and filters locally.
- **Half-days** are `half_start` / `half_start_am_pm` and `half_end` /
  `half_end_am_pm`, mapping directly onto the rota's AM and PM parts.
- `leave_requests.status` is `pending`, `approved`, `declined` or `cancelled`
  per the OpenAPI definition; a separate `cancelled` boolean also exists on both
  requests and absences. The `status=` query parameter is ignored by the server.
- Employee records carry NI number, bank details, salary and date of birth.
  Sickness records carry a type such as "Headache / migraine".

## Decisions

Settled during design, not open during implementation.

| Decision | Rationale |
|---|---|
| **Off** means the union of approved, uncancelled `/leave_requests`; `/absences`; and `/sicknesses` — deduplicated by content. **Pending requests are not shown.** | The three sources overlap without agreeing, so any one alone misses leave. Pending leave is not leave. |
| **Every local leave feature is removed**: the request form, the inbox's leave half, the entitlement report, `Clinician.leave_entitlement_sessions`, `SessionType.counts_toward_entitlement`, the leave-year settings. Swaps stay. | Breathe is the record of balances. A second one here would only disagree with it. |
| **Background sync every 15 minutes, plus an admin "Refresh now".** | No webhooks, so polling. Reading locally means the app never blocks on Breathe and keeps working when it is down. The button covers the moment someone has just approved leave and wants to fill the gap. |
| **Sickness renders as its own "Sick" chip, to everyone. The sickness type is never stored.** | Colleagues know who is off sick; it is operational. The type is health data and is dropped at ingestion, not hidden at render. |
| **Leave is an overlay table, never a rota entry.** | The alternative puts leave in two places — the entry table and the thing the resolver checks — which is the failure the last three phases removed. An overlay makes the sync a pure replace with no reconciliation. |
| **The sync fetches everything and filters locally.** | Server-side date filters disagree between endpoints, and one of them would silently miss leave spanning a window boundary. A full sync is three requests plus one per hundred rows. |
| **Linking is manual, one field, with an email match offered only as a suggestion.** | The test employees match none of the practice's clinicians, and `employee_ref` is blank on three of eleven, so nothing can be trusted to match itself. |

## Global constraints

Inherited unchanged:

- **No build step, no node, no new dependencies.** The HTTP client is `urllib.request`.
- Django 5.2 LTS, SQLite WAL, Python 3.13.
- Every colour from `tokens.css`; no literals in `components.css` or `screens.css`.
- All schedule mutations in `rota/services/*`. The sync is one.
- **Secrets from the environment only.** `BREATHE_API_KEY` and `BREATHE_API_URL`
  come from `/etc/rota.env` like `SECRET_KEY`. The key appears in no file in the
  repository and in no log line.
- **The test suite makes no network calls.** Everything runs against recorded
  fixtures.

## The model

Three tables, all written only by the sync.

**`BreatheAbsence`** — one row per Breathe record that survives filtering.

| Field | Notes |
|---|---|
| `clinician` | FK. The employee id was resolved to a clinician at sync time; records for unlinked employees are counted, not stored. |
| `start_date`, `end_date` | As Breathe gives them. |
| `half_start`, `half_start_am_pm`, `half_end`, `half_end_am_pm` | As Breathe gives them. `am_pm` is `"AM"`, `"PM"` or null. |
| `kind` | `holiday`, `other` or `sickness`. From `type` (`Holiday` / `OtherLeave`) or the endpoint. |
| `reason` | Breathe's `leave_reason.name` / `reason.name` for `other`; blank for `holiday`; **always blank for `sickness`** — the sickness type is discarded before the row is built. |
| `source_ids` | The Breathe ids this row was built from, as text — one or more, since a deduplicated row may come from two endpoints. Diagnostic only. |

A **unique constraint on the content key** — `clinician`, `start_date`,
`end_date`, and the four half-day fields — makes deduplication a database fact.
The two-endpoint overlap in the test account is exactly this key colliding.

**`BreatheLeaveMapping`** — how a record becomes a chip: `(kind, reason)` → an
ABSENCE-category `SessionType`. A row with blank `reason` is that kind's default.
Resolution is exact `(kind, reason)`, then `(kind, blank)`. Admin-editable, so a
new reason in Breathe is a row rather than a release.

**`BreatheSyncRun`** — one row per run: started, finished, `ok`, counts fetched
from each endpoint, count after deduplication, count skipped as unlinked, and
the error text if it failed. The status page reads this.

**`Clinician.breathe_employee_id`** — nullable integer, unique. Nullable because
a locum or new starter may have no Breathe record; unique because two clinicians
on one employee would give one of them the other's leave.

**Removed:** `LeaveRequest`; `Clinician.leave_entitlement_sessions`;
`SessionType.counts_toward_entitlement`; `PracticeSettings.leave_year_start_month`
and `leave_year_start_day`.

**One migration.** Adds the three tables and the link field, drops the four
removals, and seeds: three ABSENCE session types — Annual leave (`AL`), Sick
(`SICK`), Other leave (`OTH`) — created if absent, and three default mapping
rows pointing at them. There is no data to preserve, so nothing is sequenced
around protecting it.

## The client — `rota/services/breathe/client.py`

`urllib.request`, `X-API-KEY`, `Accept: application/json`, a 20-second timeout.
`fetch_all(resource)` follows `Link: rel="next"` at `per_page=100` and returns
the concatenated list under the resource's key. A 429 aborts the run with a
clear error rather than retrying — one failed sync is harmless and the next is
fifteen minutes away.

**Employees are projected at the boundary.** The client returns id, first and
last name, email, `employee_ref`, `status` and `leaving_date` and drops every
other field the moment the response is parsed. Nothing else is held anywhere.

**The client never logs a response body or the key.** Errors report the URL
path, the status code and the `x-request-id` header.

Configuration: `BREATHE_API_KEY` (no default) and `BREATHE_API_URL` (default
`https://api.breathehr.com/v1`). With no key the integration is off: the sync
command exits 0 with a message, the status page says so, and nothing else in
the app changes.

## The sync — `rota/services/breathe/sync.py`

One function, one transaction:

1. Fetch all of `/leave_requests`, `/absences`, `/sicknesses`. **Any failure
   aborts before anything is written**, and the previous overlay stands.
2. Filter: requests keep `status == "approved"` and `cancelled is False`;
   absences keep `cancelled is False`; sicknesses are all kept.
3. Normalise each to the content key plus kind and reason. Sickness type is
   dropped here.
4. Deduplicate on the content key. Sources are processed in the fixed order
   `/leave_requests`, `/absences`, `/sicknesses`, and on a collision the row
   already held keeps its `kind` and `reason`; the later record contributes only
   its id to `source_ids`. Requests go first because they carry the reason most
   reliably in the test account.
5. Resolve `employee.id` → `Clinician` via `breathe_employee_id`. Unresolved
   records are counted and dropped.
6. Delete every `BreatheAbsence` row and insert the new set. Replace-all, not
   upsert: a record cancelled in Breathe is simply absent next time.
7. Write the `BreatheSyncRun`.

**Half-days expand at read time, not at sync time.** The overlay stores Breathe's
fields; the resolver derives parts. This keeps the stored row an honest copy of
the source.

**Cadence.** A `breathe_sync` management command with `--dry-run` (fetch, dedupe,
report counts, write nothing). `deploy/rota-breathe.service` and
`rota-breathe.timer` at 15 minutes, in the shape of the backup pair.
**"Refresh now"** is an admin-only POST from the status page that runs the same
function inline and refuses if a run started in the last sixty seconds.

## The resolver becomes part-aware

`AvailabilityResolver` takes `absences` — `BreatheAbsence` rows — where it took
`leave_requests`. `leave_type(clinician_id, day)` becomes
`leave_type(clinician_id, day, part)`. For a record spanning `start..end`:

| Day | Parts covered |
|---|---|
| Strictly between start and end | AM and PM |
| Start, `half_start` false | AM and PM |
| Start, `half_start` true, `am_pm == "PM"` | PM only |
| Start, `half_start` true, `am_pm == "AM"` | AM only (a single-day morning off) |
| End, `half_end` true, `am_pm == "AM"` | AM only |
| End, `half_end` true, `am_pm == "PM"` | PM only |
| Single day (`start == end`) | Start with both; apply the start rule if `half_start`, then the end rule if `half_end`. Both flagged and consistent → that one part. Both flagged and contradictory (`AM` vs `PM`) → no parts, and the run's log notes the record — it is a Breathe data error, not something to guess at. |

The mapped `SessionType` is what `leave_type` returns, resolved through
`BreatheLeaveMapping` once per resolver construction, not per lookup.

`cell_state` passes `part` through. Its two guards keep their shape — an absence
renders only on a part the clinician works, or for a clinician with no pattern
rows at all — but the `ghost_leave` key becomes `absence` and the dashed
`is-ghost` styling goes: there is no missing entry to warn about.

## The linking admin

On the clinician form, `breathe_employee_id` renders as a **select** populated
from the employee list, cached for five minutes: "Anya Sharma · anya.sharma@… ·
EMP001". Ex-employees are listed and marked so a leaver can still be linked. If
Breathe is unreachable the field degrades to a plain integer input with a note,
so a third party being down never blocks editing a clinician.

When an **unlinked** clinician's user email exactly matches an employee email,
that option is pre-selected. Saving still requires the admin to submit. Nothing
links itself; an existing link is never overridden by a suggestion.

The clinician list gains a "Breathe" column (linked name, or a visible "not
linked") and a linked/unlinked filter.

**Unlinked clinicians have no Breathe leave and are treated as available.** That
is correct behaviour on incomplete configuration, surfaced twice: the status
page lists them, and the week grid's admin warnings gain one line — "N
clinicians not linked to Breathe" — for admins only.

## What each screen shows

**Grid.** Leave renders in the cell from the overlay, in the mapped type's tint,
as a normal chip with a title of "From Breathe". Everyone sees it. Warnings
unchanged except the unlinked line for admins.

**Day view.** The "On leave" group is derived from `cell_state`: every worked
part covered → on leave; half a day → roster with the chip in its column.

**My Schedule.** The leave balance strip and the leave rows under "Your
requests" are removed; swaps stay. The agenda and the Today box **stop
bypassing `cell_state`** and render the overlay — otherwise a GP's own leave
would be hidden from their own schedule. "On leave all week" and "Not in today"
consult it.

**Fill engine.** No logic change. `available()` asks the resolver; the resolver
reads the overlay.

**Swaps.** `swaps.validate()` gains the check it never had: refuse when either
clinician is on Breathe leave for the session they would receive, naming who
and which day.

**Inbox.** Swap half stays; leave half goes.

**Status page.** The `BreatheSyncRun` admin changelist with a header: last
successful run and counts, most recent error if any, the unlinked clinicians,
and the Refresh now button.

**Removed screens:** `/me/leave/new/`, `/requests/leave/<pk>/approve/` and
`/decline/`, `/reports/leave/`, and the "Request leave" buttons on the grid
toolbar and My Schedule.

## Documentation

`docs/admin/breathe.md`, written as the cut-over checklist in order: env vars
into `/etc/rota.env` → migrate → link clinicians → first sync → enable the timer
— because sync-before-linking yields an overlay of nothing but unlinked counts.
Plus the mapping table, the status page, and what "unlinked" means.
`docs/admin/people.md`, `session-types.md`, `day-to-day.md`,
`practice-settings.md` and the README lose their leave sections.

## Testing

**No network.** The test account's responses are recorded into
`tests/fixtures/breathe/` — employees, absences, leave requests, sicknesses, and
a paginated response with its `Link` header — including the exact two-records-
in-both-endpoints case, so dedup is tested against the real shape.

**The boundary is tested, not trusted.** A test asserts the projected employee
dict has exactly the allowed keys and none of the sensitive ones. A test asserts
a sickness row's `reason` is blank when the fixture carried a type. A test
captures log output during a failing request and asserts the key and the body
are absent.

**Behaviour:** the half-day table above, row by row, through the resolver;
dedup collapsing the overlap fixture to one row with both ids; `pending` and
`cancelled` excluded; a failing fetch leaving the previous overlay row-for-row
intact; unlinked employees counted and the admin warning rendered; swaps refused
onto leave with the message naming the clinician; My Schedule rendering the
GP's own overlay leave — the case the old bypass hid.

**Removal:** the old URLs return 404; the dropped fields raise on access; a grep
over `rota/` for `LeaveRequest` finds nothing.

**The no-pre-existing-test-edits rule cannot hold for a removal**, so the
replacement rule is stated: tests whose subject is removed are removed; tests
whose fixture was a `LeaveRequest` get a `BreatheAbsence` fixture and keep their
assertions word for word; no assertion is weakened.

## Deferred

- **Pending requests shown as tentative.** Declined for now; the data is there
  if wanted later.
- **A leave balance from Breathe's allowances.** Declined; GPs use Breathe.
- **Retry with backoff on 429.** Not needed at fifteen-minute cadence.
