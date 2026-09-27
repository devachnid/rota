# Practice HR: foundation and absence — design

**Date:** 2026-09-27
**Status:** approved in conversation; spec for review
**Home:** written here until the new repository exists, then moved with the
code. The rota keeps a pointer to it.

The practice manages leave in BreatheHR, and the rota reads it from there
(`2026-09-02-breathe-leave-design.md`). Breathe cannot express the practice's
allowance rules, its payroll output needs manual work each month, and the
practice wants its data and workflows under its own control. This spec is the
first of a set that replaces Breathe with a system the practice owns.

## The set, and where this spec sits

Decided in conversation before design started. Each item is its own spec, plan
and build, in this order.

1. **Foundation and absence** — this spec. People, employments, contracts,
   working patterns, roles and sign-in; the absence ledger, requests,
   approvals, the calendar and the payroll changes report. The first release
   replaces Breathe's leave function end to end.
2. **Rota integration** — the rota reads people, working patterns and
   approved absences from this system instead of Breathe, and sends sessions
   worked back for TOIL. Built straight after this one, before GPs move their
   leave across.
3. **Onboarding, offboarding and documents** — checklist templates by role,
   checks with expiry dates, a document store with read-and-sign.
4. **Training compliance** — role-to-course matrix, evidence, renewals, and
   the reminder engine shared with item three.
5. **Later** — sickness case management, appraisals, restricted case files.

## Decisions made in conversation

| Decision | Rationale |
|---|---|
| **A separate Django project in its own repository**, own database, own deployment on the rota's LXC-and-tunnel pattern. Not apps inside the rota. | The rota models GPs only and deliberately holds almost no personal data. An HR system covers every employee and holds health, DBS and bank data. Putting that into the app every GP opens daily inverts the population and undoes the September decision that the rota holds no leave balances. |
| **The HR system is the identity provider.** It serves OpenID Connect; the rota becomes a relying party. The rota's `accounts` app moves here wholesale. | GPs will not accept two logins. The HR system holds every employee anyway, and the passkey, invitation and lockout work already exists in `accounts`. No shared package is needed. |
| **Units are per contract type**: sessions for GPs, hours for everyone else. Entitlement is expressed in **weeks per year** and multiplied by the contracted weekly amount. | One formula covers both units and pro-rates part-timers without a special case. |
| **Accrual is a day-by-day integral** over the leave year. | Service tiers stepping mid-year, fixed terms ending, starters, leavers and hours changes are all one calculation. |
| **Every balance is a sum of ledger lines.** No stored balance field. Lines are never edited; corrections are new lines. | Tiered allowances, payroll reporting and audit all need to answer "why is this number what it is". |
| **Working patterns live here and are the master.** The rota will read them (spec 2). | The admin must not record a pattern in two places. |
| **Employments are dated spells** with their own continuous-service date. | People leave and come back; reckonable service is not always the start date. |
| **Contracts may overlap** and the contracted amount on a day is their sum. | "18.75 hours permanent plus 18.75 hours fixed term for twelve months" is a real contract. |
| **Partial-day absences** are allowed for hours-based staff, as hours on a single day. Sessions-based staff book in half days. | 1.5 hours of dependants' leave happens; a session is the smallest thing a GP's allowance expresses. |
| **Payroll is an external bureau** that takes a monthly changes report. The system records dates and units and does no statutory pay arithmetic. | That is what the bureau needs, and it keeps SSP, SMP and OSP rules out of this codebase. |
| **Everyone self-serves; line managers approve; the practice manager oversees.** | As asked. |
| **SQLite with WAL and a filesystem document store**, as the rota. | At one practice's headcount it is plenty and the backup tooling exists. Postgres only if concurrency ever shows. |

## Global constraints

Inherited from the rota unless stated.

- Django 5.2 LTS, Python 3.13, SQLite WAL. Unfold for the admin. No build
  step, no node. Every colour from `tokens.css`.
- **Secrets from the environment only.** No key, token or password in any file
  in the repository or in any log line.
- **All writes to `people` and `absence` go through `*/services/`**, never a
  view, a form's `save()` or the admin directly. The admin is a thin layer over
  the services for the few things it edits.
- **The test suite makes no network calls.**
- **New dependencies are allowed but named here.** `django-oauth-toolkit` for
  OpenID Connect. `openpyxl` for the payroll spreadsheet. Nothing else without
  a spec change.
- The rota's own constraints continue to apply to the rota; the one rota change
  in this release (sign-in through OpenID Connect, one client library) is
  specified in section 3 and is the whole of it.

## 1. Architecture

A new Django project, working name **`practice-hr`**, hostname to be chosen,
with three apps:

- **`accounts`** — the rota's app, moved: email login with a case-insensitive
  unique constraint, invitation links, self-service passwords with a throttled
  reset, passkeys, `django-axes` lockout, and the `is_rota_admin` flag renamed
  `is_hr_admin`. Plus the OpenID Connect provider (section 3).
- **`people`** — employees, employments, positions, contracts, contract types,
  working patterns, pay records, teams, the audit log (section 2).
- **`absence`** — absence types, policies, pots, the ledger, absences,
  requests, the calendar, bank holidays and closed days, year end, the payroll
  report (sections 4 to 6).

Deployment mirrors the rota's `deploy/` directory: a gunicorn unit, a backup
timer that copies the SQLite file and the document directory, a
`clearsessions` timer, a nightly `hr_nightly` timer (section 3 and 5), and the
same `/etc/<name>.env` secrets file.

Boundaries that hold for the whole release:

- **This system is the record for people and absence.** The rota keeps its
  own clinician table and pattern rows until spec 2 lands; nothing in the rota
  changes here except sign-in.
- **Health data stays minimal.** A sickness absence holds dates and a coarse
  category from a short fixed list. No free text, no fit notes. Those are a
  later, restricted feature.
- **Effective dating everywhere it matters.** Employments, positions,
  contracts, patterns, pay records and policies carry a from-date and an
  optional to-date. Any question can be asked "as of a day".
- **The read API for the rota is part of this release** (section 7) so its
  shape is fixed now, even though the rota consumes it in spec 2.

## 2. People

All in `people/models/`. Nothing here is ever deleted; rows end.

**`Employee`** — the person, created once.
`first_name`, `last_name`, `preferred_name`, `work_email` (unique, the login
identity), `personal_email`, `phone`, `date_of_birth`, address fields,
`ni_number`, `user` (one-to-one, nullable). `EmergencyContact` is a child table
(name, relationship, phone, priority).

**`Employment`** — one dated spell of employment.
`employee`, `start_date`, `end_date` (nullable), `leaving_reason` (choices:
resigned, retired, end of fixed term, dismissed, redundancy, death in service,
other), `continuous_service_date`. The service date defaults to `start_date`
and is edited when reckonable service carries over from elsewhere in the NHS
or from an earlier spell. Spells for one employee cannot overlap. "Current
employment" means the spell containing today; an employee with none is a
leaver, and a new spell makes them a returner with all earlier history intact.
Service tiers read the current spell's `continuous_service_date`.

**`Team`** — name, `display_order`, optional `min_present` (section 5).

**`Position`** — a dated job.
`employment`, `title`, `team`, `line_manager` (FK `Employee`, nullable),
`primary` (boolean), `from_date`, `to_date`. One employment may hold two
positions at once, exactly one of them `primary` on any day. The
**reporting line** on a day is the `line_manager` of the position active that
day; with two positions, the one flagged `primary`. A person cannot be their
own manager, and the chain is checked for cycles on save.

**`ContractType`** — configurable, seeded with Partner, Salaried GP, GP
trainee, Practice nurse, HCA, Reception, Administration, Management.
`name`, `unit` (`sessions` or `hours`), `full_time_weekly` (9 sessions, 37.5
hours, editable), `display_order`. The default policy set hangs off it
(section 4).

**`Contract`** — a dated contractual arrangement; rows may overlap.
`employment`, `contract_type`, `basis` (`permanent` or `fixed_term`),
`from_date`, `to_date` (required for fixed term), `weekly_amount` in the type's
unit, `notes`. **Rule:** all contracts of one employment active on the same
day share a unit; the service refuses a second unit. **Derived:**
`contracted_amount(employment, day)` is the sum of `weekly_amount` over
contracts active that day; `fte(employment, day)` divides it by the type's
`full_time_weekly`. Neither is stored.

**`WorkingPattern`** — a dated version of the whole working week.
`employment`, `effective_from`, `cycle_weeks` (always 1 in this release; the
column exists so alternating weeks can be added without a rebuild), and seven
**`PatternDay`** children: `weekday`, `week_in_cycle` (always 0),
`am_units`, `pm_units` (decimal, in the employment's unit; for sessions each
is 1 or 0). The pattern in force on a day is the version with the greatest
`effective_from` on or before it. A warning, not an error, shows when a
version's weekly total differs from `contracted_amount` on its
`effective_from`. Half-day names (`AM`, `PM`) match the rota's `Part`.

**`PayRecord`** — dated pay, restricted to HR admins.
`employment`, `from_date`, `to_date`, `basis` (annual, hourly, per session),
`amount`, `reason`. No arithmetic; it exists so the payroll report can list
pay changes with effective dates.

**`AuditEntry`** — `actor`, `at`, `model`, `object_id`, `field`, `before`,
`after`, `note`. Written by every service function in `people` and `absence`,
one row per field changed, and one row of kind `viewed` for each view of a pay
or health section. Read-only in the admin; never deleted.

### Admin

Unfold. Employee is the hub: inlines for employments, and on each employment
inlines for positions, contracts and pattern versions, with a pattern grid
widget (seven days by two halves, decimal cells). Pay records are an inline
visible only to HR admins. The audit log is a filterable list. Every model
edit posts through its service.

## 3. Roles, access and sign-in

**Roles** on the login account: **HR admin** (set by an HR admin; the practice
manager and a deputy), and **employee** (everyone with an account).
**Approver** is not set: an account is an approver on a day if its employee is
the `line_manager` of at least one position active that day. A superuser
exists for setup and break-glass only and is never used day to day.

**What each role sees.**

| | Employee | Approver (for direct reports) | HR admin |
|---|---|---|---|
| Own record | Personal details editable; employment, positions, contracts, pattern read-only; pay hidden | — | Everything |
| Reports' records | — | Without pay and NI number | Everything |
| Balances and ledger | Own | Reports' | All |
| Requests | Own; submit, cancel | Reports'; decide | All; decide, adjust |
| Sickness | Own dates and category | Reports' dates and category | All |
| Calendar | Team and practice, names and calendar labels only | Same | Same plus type detail |
| Pay, NI, health sections | — | — | Yes; each view audited |

**Approval routing.** A request goes to the requester's line manager as of
today. If there is none, or the requester is at the top of their own chain,
it goes to the HR admin group. An approver never sees their own request. An
HR admin can decide any request. Delegation while a manager is away is
deferred; the admin override covers it.

**Sign-in.** `accounts` as moved from the rota. The **OpenID Connect
provider** is `django-oauth-toolkit` with its OIDC support enabled: RS256
keys from the environment, the authorization-code flow only, one confidential
client registered for the rota, consent skipped for first-party clients. The
ID token and the `userinfo` response carry `sub`, `email` and `employee_id`
and nothing else. Passkeys are registered and used here only.

**The rota change**, the only one in this release: the rota adds one OpenID
Connect client library (chosen at planning; `mozilla-django-oidc` is the
default candidate) and a *Sign in with the practice account* path. On first
sign-in it matches `email` case-insensitively to an existing rota user, or
creates one with no usable password. `is_rota_admin` stays local to the rota.
The rota's own password form remains only for the superuser. Rota passkeys are
retired once every account has signed in through the HR system; the code is
removed in spec 2.

**Housekeeping.** `hr_nightly` disables the login of any employee whose
current employment ended before today and who has no later spell. Retention
periods are a setting per category (personal, pay, health, audit), and a
report lists what is past its period; deletion is manual in this release.

## 4. The absence ledger

All in `absence/models/`; every write through `absence/services/`.

**`AbsenceType`** — configurable, seeded with: Annual leave, Bank holiday,
Study leave, TOIL, Sickness, Maternity, Paternity, Shared parental, Adoption,
Compassionate, Dependants, Unpaid, Other.
Flags: `paid`, `uses_pot`, `needs_approval`, `self_certified`,
`calendar_label` (what colleagues see: "Leave", "Sick", "Away"),
`payroll_reportable`, `health_sensitive`, `display_order`, `active`.

**`Policy`** — the rules as data, per `(contract_type, absence_type)` for
pot-backed types, effective-dated.
`weeks_per_year` (decimal; statutory minimum 5.6), `leave_year_basis`
(`fixed` with `year_start_month`/`day`, or `anniversary` of the current
employment's start), `carry_over_max_weeks` (nullable), `carry_over_expires_after_days`
(nullable), `rounding` (nearest 0.25 hour or 0.5 session; configurable),
`bank_holiday_handling` (`closed_not_charged`, `pro_rata_pot`,
`included_in_annual`), `toil_expires_after_days` (TOIL policies only).
**`PolicyTier`** children: `after_years` of continuous service,
`extra_weeks`. The tier in force on a day is the highest `after_years` the
person has reached by that day.

**Accrual — one function, `accrual.entitlement(pot)`**, pure, over the pot's
leave year:

    for each day d in [year_start, year_end]:
        if the employment is not active on d: rate = 0
        else:
            weeks = policy.weeks_per_year + tier_extra(service_date, d)
            weekly = contracted_amount(employment, d)      # sum of contracts active on d
            rate = weeks * weekly / days_in_year
        total += rate
    return round(total, policy.rounding)

Because `weekly` reads every contract active that day, and `weeks` reads the
tier that day, a mid-year tier step, a fixed term ending, a starter, a leaver,
concurrent contracts and an hours change are the same loop. The bank-holiday
pot under `pro_rata_pot` uses the same loop with `weeks` replaced by the
number of bank holidays in the leave year divided by five, so a full-timer
accrues one working day per bank holiday and a part-timer their fraction.

**`Pot`** — `employment`, `absence_type`, `year_start`, `year_end`, `unit`.
Unique on the first four. Created by the service the first time anything
needs it. No balance field.

**`LedgerEntry`** — the only thing that changes a pot.
`pot`, `date`, `kind` (`entitlement`, `revision`, `carry_in`, `expiry`,
`booking`, `cancellation`, `toil_earned`, `toil_taken`, `adjustment`),
`units` (signed decimal), `absence` (FK, nullable), `note`, `actor`,
`created_at`. **Never edited or deleted.** Balance is
`sum(units)`; the balances page splits it by kind and by whether the absence
is past or future.

**Entitlement and revisions.** `services.sync_entitlement(pot)` computes
`accrual.entitlement(pot)`, subtracts the sum of existing `entitlement` and
`revision` lines, and if the difference is non-zero writes one `revision`
line (or the first `entitlement` line) with a note naming the cause
("contract 18.75h fixed term ended 2027-03-31"). It is idempotent and is
called by every service that changes a contract, tier, policy or employment,
and by `hr_nightly` for every open pot as a safety net.

**`Absence`** — the booking.
`employment`, `absence_type`, `status` (`requested`, `approved`, `declined`,
`cancelled`), and one of two shapes:

- **Range:** `start_date`, `end_date`, `start_half` (`AM` or blank),
  `end_half` (`PM` or blank), matching the rota's halves.
- **Partial day:** `start_date == end_date`, `start_time`, `end_time`,
  `hours`. Allowed only when the employment's unit is hours.

Plus `cost_units` (computed on approval from the pattern in force on each
day, and stored), `requested_at`, `requested_by`, `decided_at`,
`decided_by`, `decision_comment`, `cancelled_at`, `cancelled_by`. Sickness
adds `category` from a short fixed list (illness, injury, mental health,
surgery or procedure, pregnancy-related, other) and `self_certified`
(true for the first seven calendar days). Family-leave types add
`expected_start`, `actual_start`, `expected_return`, and a **`KitDay`** child
table (date). Overlapping approved absences for one employment are refused by
the service.

**Costing — `costing.cost(absence)`**, pure. For a range: for each day, for
each half the absence covers, add that half's pattern units, unless the day
is a bank holiday under `closed_not_charged` or a practice closed day. For a
partial day: `hours`, capped at the sum of the halves it touches. The cost is
stored on approval. A later pattern change never re-prices an approved
absence; an HR admin can re-cost, which writes an `adjustment` line with the
difference and a note.

**`BankHoliday`** — `date`, `name`, `nation` (England and Wales seeded for
the coming years; editable). **`ClosedDay`** — `date`, `reason`, for
practice closures beyond bank holidays.

**Bank holidays are charged automatically.** Under `pro_rata_pot` and
`included_in_annual`, the service creates an approved `Bank holiday` absence
for each bank holiday on which the pattern in force has units, costed from
that pattern and drawing on the bank-holiday pot or the annual pot
respectively. It runs when a pot is created, when a pattern version is saved,
and nightly for the year ahead, and it removes its own absences (with a
`cancellation` line) when a pattern change makes a bank holiday a non-working
day. Under `closed_not_charged` no absence is created and the costing loop
skips the day.

**Pot-less types** (sickness, family leave, compassionate, dependants,
unpaid, other) create an `Absence` and no ledger line. They show on the
calendar and the payroll report.

## 5. Requests, approvals and the calendar

**Requesting.** The employee picks a type and either a date range with
half-day markers or, if their unit is hours, a single day with times. The
form shows `cost`, the balance after, a warning if that would be negative,
and a refusal if the dates overlap an existing absence. Pot-less types skip
the balance. Submission writes the `Absence` as `requested` and emails the
approver. Types with `needs_approval` false (sickness, dependants by default)
are written `approved` at once, by the employee on return or by their
manager on the day.

**Deciding.** The approver's queue lists requests routed to them with the
requester's balance, the team calendar for the dates, and who else on the
team is off. Approve writes, in one transaction, the status, the cost, and
the `booking` line; decline writes the status and comment and no line. Both
email the requester. A waiting request older than a set number of working
days (a setting, default three) is listed on the HR admin dashboard and
emailed once.

**Cancelling.** The employee may cancel an approved absence until its start;
an HR admin at any time. Cancellation writes a `cancellation` line for
exactly `cost_units` and emails the approver.

**Calendar.** A month view for a team or the practice: each day lists who is
off with the `calendar_label` only, a count, and, where the team has
`min_present`, a warning when approving would leave fewer present. The
approver sees this in the decision screen.

**Balances.** Per employee and per team, for the current and next leave
year: entitlement, carried in, taken (approved, past), booked (approved,
future), pending, remaining. Every figure links to the ledger lines behind
it.

**Year end.** `manage.py absence_year_end`, run by `hr_nightly`, closes each
pot whose `year_end` was yesterday: writes `carry_in` to the next year's pot
up to `carry_over_max_weeks` converted to units on the year's first day, and
`expiry` for the remainder. Carried-in units get their own `expiry` line on
`carry_over_expires_after_days` if any remain unbooked by then, which the
nightly job also checks. TOIL earned lines expire by `toil_expires_after_days`
from their date, the same way. Every automatic line is reversible by an
`adjustment`.

**Emails** go through a `mail.py` copied from the rota's pattern: never raise
into a page, log the failure, and show the admin the link on screen when no
relay is configured.

## 6. Payroll report, errors and testing

**Payroll changes report** — `absence/services/payroll.py`, a page and a
management command. For a pay period (a month by default): starters with
contract type, amount and start; leavers with last day and reason; contract
changes with effective dates; pay changes from `PayRecord`; every sickness
absence with dates and whether self-certified; every unpaid absence with dates
and units, partial hours as entered; family leave with expected and actual
dates and KIT days; TOIL earned and taken where the type is paid. Output is
an `.xlsx` with a fixed column set agreed with the bureau (one sheet per
section), saved under `media/payroll/<period>.xlsx` with a row in
**`PayrollRun`** (period, generated_at, by, row counts) so the same report can
be reproduced. Health-sensitive category never appears; only dates.

**Errors.**

- Every service function that writes to the ledger runs in one transaction;
  a failure leaves no line.
- Overlaps, wrong-unit contracts, self-management and cycle in the reporting
  line are refused in the service, not only in forms.
- Assigning a contract whose type has no policy for a pot-backed type in use
  is a validation error naming the missing policy, never a silent zero.
- The read API (section 7) is read-only, so a rota fault cannot change HR
  data.
- A failed email is logged and shown on the dashboard; it never blocks a
  decision.

**Testing.**

- `accrual.entitlement` and `costing.cost` are pure functions tested against a
  table of worked cases: full-timer, part-timer, mid-year starter, mid-year
  leaver, tier step in month seven, fixed term ending in month nine,
  concurrent contracts, hours and sessions, anniversary and fixed leave
  years, a bank holiday under each handling, a partial day, a range starting
  PM and ending AM.
- Ledger properties: balance equals the sum of lines; cancellation restores
  exactly; `sync_entitlement` is idempotent and writes exactly one revision
  per cause; year end carries and expires to the unit.
- Access and routing through the Django test client for each role, including
  the top-of-chain and no-manager cases and the "approver never sees own
  request" rule.
- The OIDC flow with the rota is tested at the rota end against a recorded
  discovery document and token response; no network.
- No pre-existing rota test assertion is weakened by the sign-in change.

## 7. The read API for the rota (shape fixed here, consumed in spec 2)

Token-authenticated (a per-client secret from the environment), JSON,
read-only, versioned under `/api/v1/`:

- `GET /people` — id, names, work email, contract type, unit, current
  employment start and end, active positions' titles and teams.
- `GET /patterns?employee=` — every pattern version with `effective_from` and
  its fourteen half-day cells.
- `GET /absences?from=&to=` — approved absences overlapping the window, with
  the range or partial-day shape, `calendar_label`, and for sickness the word
  "Sick" and never the category. Pending requests are included with
  `status: requested` so the rota may show them as a hint; the rota decides.
- No push endpoint in this release: the rota polls every fifteen minutes as
  it does with Breathe, plus a "Refresh now". A push can be added in spec 2.

## Documentation

`docs/admin/` in the new repository, one page per area as the rota's:
people, contracts and patterns, policies and tiers, requests and the
calendar, year end, payroll, sign-in and roles. Each field explained with
what depends on it and what goes wrong if it is set wrong. The rota's
`docs/admin/` gains a page on signing in with the practice account.

## Not done, on purpose

- Alternating-week patterns (`cycle_weeks` exists; the UI and costing for it
  do not).
- Delegated approval while a manager is away.
- Statutory pay arithmetic of any kind.
- Free-text sickness reasons, fit notes, return-to-work interviews, Bradford
  factor, trigger reviews.
- Documents, onboarding checklists, training records (specs 3 and 4).
- Buying and selling leave.
- Automatic deletion under retention policy.
- Push notification of the rota; a webhook or event feed is spec 2's call.
- Sessions worked flowing back from the rota for TOIL (spec 2).
- Multi-practice or multi-tenant anything.
