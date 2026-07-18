# GP Rota Webapp — Design

**Date:** 2026-07-18
**Status:** Approved design, pre-implementation

## Purpose

Replace the practice's spreadsheet-based GP rota with a self-hosted webapp that is
easier to maintain and analyse. The app manages session-based scheduling for the
practice's GPs, assists with fair allocation of duty sessions, handles leave and
swap requests, and reports on duty fairness, leave, and staffing levels.

## Users and scale

- ~5–15 GPs at one practice (plus occasional locums).
- **Admin** (rota manager) edits the rota and approves requests. Admin is a
  *flag on an account*, not a separate identity: a GP can also hold admin rights,
  and a practice manager can be an admin with no clinician profile.
- **GPs** view the published rota and submit leave/swap requests.
- Locums can appear on the rota as clinicians without login accounts.
- Accounts are created by an admin; there is no self-signup.

## Core domain model

The rota has two layers:

1. **Availability pattern** (stable): which sessions (weekday × AM/PM) each GP
   works. Changes rarely; changes are effective-dated to preserve history.
2. **Allocation** (per period): what each GP does in each of their available
   sessions — e.g. Routine surgery, Duty, Ward round, Visits, Admin, CPD — or an
   absence (Annual leave, Study leave, Sick). Rebuilt each rota period, with
   assisted auto-fill.

The basic unit of the rota is the **session**: a date plus AM or PM.

### Duty

- Duty is *usually* worked as a full day (AM + PM by the same GP) but can
  occasionally be split between two GPs.
- Assisted fill always drafts duty as a linked full-day pair of entries.
- Editing one half of a linked pair (e.g. reassigning the PM) splits it into two
  independent per-session entries.
- Duty coverage is checked per-session: a day is covered when AM and PM each
  have a duty entry, whether from one GP or two.

### Fairness

- Only **Duty** is fairness-tracked in v1. The mechanism (a flag on
  SessionType) supports adding other types later without code changes.
- Fairness is counted in **sessions** (full duty day = 2, split half = 1).
- Fair share is **weighted by sessions worked**: a GP working 4 sessions/week
  owes half the duty of one working 8.

## Architecture

- **Stack:** Python 3.12, Django 5.x (LTS), SQLite (WAL mode), htmx for grid
  interactivity, server-rendered templates, minimal hand-rolled CSS. No node
  build step, no Redis/Celery/background workers.
- **Layout:** one Django project (`config`) with a single app (`rota`).
- **Serving:** gunicorn behind the existing Cloudflare tunnel on the current
  LXC container; static files via WhiteNoise; HTTPS terminated at the tunnel.
- **Backups:** nightly `sqlite3 .backup` copy via a systemd timer.
- **Timezone:** Europe/London.
- **UI evolution:** grid mutations are granular endpoints (e.g.
  `POST /rota/assign`) so drag-and-drop or a richer grid component can be layered
  on later without backend changes.

## Data model

- **User** — Django auth user (email + password) with an `is_rota_admin` flag.
- **Clinician** — name, initials (grid display), active flag, optional link to a
  User, annual leave entitlement in sessions per leave year.
- **SessionType** — name, category (clinical / non-clinical / absence), display
  colour, short code, `fairness_tracked` flag (v1: on for Duty only). Managed as
  data via the setup screens, not code.
- **Site** — practice sites; optional field on a rota entry.
- **PatternSlot** — clinician × weekday × AM/PM × effective-from date: the
  availability layer.
- **RotaEntry** — date, AM/PM, clinician, session type, optional site, optional
  free-text note, draft/published flag, `manually_set` flag, optional
  allocation-group id linking a full-day duty pair. Database-enforced uniqueness:
  one entry per clinician per session.
- **DayNote** — one free-text note per date, shown in the day header on the grid
  (e.g. "Flu clinic", "CQC visit"). Admin-edited, visible to all, usable on
  future dates for forward planning.
- **LeaveRequest** — clinician, date range, leave type, message, status
  (pending → approved / declined), admin comment. Approval writes absence
  entries over the GP's patterned sessions in the range.
- **SwapRequest** — names two sessions: one where the proposer holds the
  assignment they want to give up, one where the colleague holds theirs. On
  apply, the two clinicians **exchange session types in both sessions** (e.g. B
  takes A's Tuesday duty and A takes B's Thursday duty, each absorbing the
  other's displaced session). Valid only when both GPs work both sessions
  involved. Status chain: proposed → colleague accepted → admin approved →
  applied; a decline by either party ends it. A linked duty-day pair swaps as a
  whole day.
- **CoverageRule** — session type, applicable days, unit (*per-session* or
  *per-full-day*), required count. Initial defaults (to confirm against real
  practice data, editable as data): Duty = 1 per day (full-day unit, every open
  day); Ward round = 1 per session on its scheduled days.
- **ClosedDay** — bank holidays and practice closures; greyed on the grid,
  skipped by assisted fill. Manually maintained.
- **Practice settings** — minimum clinical GPs per session (drives staffing
  warnings), leave-year start date (default 1 April), default fill session type
  (Routine surgery).
- **Change log** — who changed which rota entry, when, from what to what.

Leave balances and fairness tallies are always computed from entries, never
stored, so they cannot drift out of sync.

## Screens

1. **Rota grid** (the heart): week view, clinicians as rows, days × AM/PM as
   columns. Colour-coded session codes; merged cell for a linked duty day;
   greyed cells outside a GP's pattern; day headers carry DayNotes, closed days,
   and live warnings (no duty cover, below minimum staffing). Week navigation
   plus jump-to-date.
   - *Admin:* click a cell → popover to set session type / site / note; drafts
     rendered hatched until published; publish-period action.
   - *GP:* read-only published view, own sessions highlighted, buttons to
     request leave or a swap.
2. **My schedule** — personal upcoming sessions, leave balance, own pending
   requests, and any swap proposals awaiting the user's acceptance.
3. **Requests inbox** (admin) — pending leave/swap requests with approve /
   decline. Approving shows exactly what will be overwritten (e.g. "replaces 4
   booked sessions incl. Tuesday Duty — this leaves a duty gap").
4. **Assisted fill** — pick a date range, optionally tick "fill remaining empty
   cells with Routine surgery", run, review drafts on the grid, publish.
5. **Reports** — see below.
6. **Setup** — Django admin (lightly styled) for clinicians, session types,
   sites, patterns, coverage rules, closed days, users, settings. No custom UI
   effort here.

## Assisted fill

A deliberately simple, explainable greedy algorithm — not a constraint solver:

1. Walk each slot required by coverage rules across the chosen range in date
   order.
2. **Eligibility:** available per pattern for the whole allocation unit (both
   sessions for a full duty day), not on leave, not a closed day, and not
   already holding a duty allocation that day (prevents the filler stacking two
   duty halves on one GP in a day).
3. **Duty ranking:** eligible GPs ranked by fairness deficit — weighted fair
   share minus actual duty sessions over the previous 3 months plus the current
   draft. Tie-break: longest time since last duty.
4. **Ward round (not fairness-tracked):** filled by simple rotation among
   eligible GPs.
5. All output is **draft** entries, visible only to admins until published.
   Slots with no eligible GP are flagged red for manual resolution.
6. Optional final pass fills remaining empty available cells with the default
   session type (Routine surgery).

**What fill may touch:** fill writes only into empty cells and replaces only its
own previous drafts. It never overwrites published entries or manually-set
entries (flagged `manually_set`), so re-running is always safe. Draft cells show
their reasoning on hover ("Dr K: 1.5 duty sessions below fair share").

Design bet: a transparent rule the admin can predict beats a clever solver they
have to fight. Hand-tweaking the draft on the grid is expected and cheap.

## Reports

All computed live from entries, filterable by date range:

1. **Duty fairness** — per GP: duty sessions done vs weighted fair share, with a
   running balance so the admin can see who is owed an easier week.
2. **Leave** — per GP: entitlement vs taken vs booked-ahead for the leave year;
   plus a "who's off when" overview to spot crunch weeks before approving more
   leave.
3. **Staffing** — sessions below minimum staffing or missing duty cover, listed
   forward in time so gaps surface weeks early.

## Auth and security

- Django built-in auth: email + password, session cookies, CSRF protection.
- Login rate limiting via django-axes.
- Admin-created accounts; passwords resettable by an admin.
- Roles: `is_rota_admin` flag grants edit rights; all authenticated users get GP
  view rights. Draft entries and the requests inbox are admin-only.
- App is internet-exposed via Cloudflare tunnel; HTTPS enforced at the tunnel.
- No patient data is stored — the app holds staff names, schedules, and leave.

## Error handling philosophy

- **Hard rules at the database:** one entry per clinician per session; valid
  request state transitions.
- **Soft problems are warnings, never blocks:** staffing gaps, fairness drift,
  and leave clashes are flagged but always overridable — real practices have
  exceptional weeks.
- Destructive actions (approving a request that overwrites entries, re-running
  fill) always preview their effect before confirmation.
- Every rota entry change is recorded in the change log.

## Testing

- pytest + pytest-django.
- **Thorough unit tests** on the pure logic: assisted-fill eligibility, fairness
  weighting and deficit ranking, re-run safety, leave balance and staffing
  calculators.
- **Workflow tests** via the Django test client: leave approval overwriting
  entries, the swap state chain, draft/publish visibility, permission
  boundaries (GP vs admin).
- Light smoke tests on remaining views.

## Out of scope for v1 (future candidates)

- Email/notification delivery — v1 surfaces pending actions in-app on login.
- Drag-and-drop grid editing (architecture supports adding it later).
- Fairness tracking for session types beyond Duty (flag exists; just enable).
- Automatic bank holiday import.
- Rotating multi-week patterns; sessions-vs-contracted reporting.
- Nurses/HCAs/reception scheduling; multi-practice support.
- ICS calendar feeds for GPs' personal calendars.
