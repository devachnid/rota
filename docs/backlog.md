# Post-merge backlog

**Last checked against live code: 2026-09-04.** Entries here have gone stale
before — two were already fixed when checked, this file claimed the app was
undeployed for a day after it went live, and it listed Frontend Phase 2 as
"not started" three days after it merged. Verify before acting on anything
recorded here. On 2026-09-04 the two open items were re-checked against the code
(both still open then; both fixed on 2026-09-05) and everything the day's eight
merges parked was added.

Three sweeps on 2026-08-23 cleared everything actionable that the v1 and
autofill v2 review processes had accumulated:

- **Nine user-visible defects** — stuck swap proposals, backwards leave ranges,
  the unreadable unfilled list, false "behind target" readings, lost note/site
  on the eligibility warning, the stage-rule crash, orphaned locum re-booking,
  dead leave/swap links.
- **Six correctness edges** — fairness seeding blind to in-range entries,
  half-covered full-day double-cover, the 29 Feb leave-year crash, whole-range
  trainee accrual seeding, a non-monotonic rotation tie-break, inactive
  clinicians surviving in eligibility pools.
- **The structural tidies** — the duplicated availability rule consolidated into
  one `PatternResolver`, site precedence and the trainee-pass skeleton extracted,
  `swaps.validate()` made single-pass, plus assorted query and validation
  hygiene and the test-coverage gaps earlier reviews flagged.

## Settled

- **A stored weekday or month list that no longer parses stops at deploy**
  (2026-09-05). The post-deployment fixes (2026-08-31) gave
  `PracticeSettings.open_weekdays` and `CoverageRule.months` / `weekdays` /
  `preferred_weekdays` a strict parser, and a value stored under the old rules
  — a trailing comma — 500'd the grid, the day view and My Schedule, none of
  which turn a parse failure into a 400. `rota.E006` in `check --deploy` now
  reads every stored value and names each bad record and field; the fix is to
  open it in the admin and save. The views stay undecorated on purpose: the
  check closes all three routes and any future one at once.

- **Closed-day headers are one tone** (2026-09-05). The AM/PM header cells
  under a closed day now carry `closed` like the day-name cell above them.

- **Login accounts are invited, passwords are self-service, and passkeys are a
  second way in** (2026-09-04, PRs #10–#13; spec
  `docs/superpowers/specs/2026-09-04-account-access-design.md`). An admin
  creates an account with an email and an Admin-status tick and never sees a
  password; the person sets theirs from a seven-day single-use link, resets it
  from the login page, and can enrol passkeys, which the login page offers in
  the email field's autofill. Outgoing mail is Django's SMTP backend (Mailjet
  on staging) and the app works without it — the admin copies each link. Two
  things staging found the same evening are settled with it: a sender with an
  unquoted `@` in its display name made every send raise (now caught, logged,
  and refused by `check --deploy` as `rota.E005`), and the failed send was
  stamping the account so the retry was silently throttled (a failed public
  send no longer stamps).

- **The username half of the login lockout had never worked** (2026-09-04:
  the key in PR #11, the failure log in PR #13). See the correction under the
  axes entry below.

- **CI gates every merge** (2026-09-04, PRs #14 and #15). `tests` runs
  `ruff check` (pyflakes only), `makemigrations --check`, the suite, and
  `collectstatic` + `check --deploy` against a throwaway environment; the
  master ruleset requires it strictly, alongside CodeQL, a pull request and
  linear history. The only merge method is rebase.

- **Leave moved to BreatheHR** (2026-09-02). Requesting, approving and
  tracking entitlement locally is gone — `LeaveRequest` and its "counts
  toward entitlement"/leave-year machinery are deleted, and leave is now
  read from Breathe every fifteen minutes into a read-only overlay
  (`BreatheAbsence`) that the availability resolver consults directly.
  Leave is deliberately **not** written as rota entries: putting it in the
  entry table as well as the overlay would be two answers to one question,
  the exact failure the earlier availability consolidation (pattern slot vs.
  rota entry) exists to prevent. An unlinked clinician is treated as
  available rather than blocking the sync, with the status page and grid
  warning admins instead.

- **Axes now locks by address as well as username** (2026-08-26). The earlier
  decision — username only, because behind the tunnel every request carries the
  tunnel's IP — was correct about the symptom and wrong about the fix: axes was
  falling back to `REMOTE_ADDR` because django-ipware is not installed.
  `AXES_CLIENT_IP_CALLABLE` resolves `CF-Connecting-IP` with no new dependency,
  and `AXES_RESET_ON_SUCCESS` keeps a shared surgery NAT address from locking
  the building out. Verified end to end: five failures across five different
  usernames from one address now blocks it, and an unrelated address is
  unaffected. Clears the `axes.W006` system check.
  **Correction, 2026-09-04:** that verification exercised only the address
  key. With a custom `USERNAME_FIELD`, django-axes recorded attempts under
  `credentials["email"]` while Django's login form sends
  `credentials["username"]`, so every row carried `username=None` and the
  username key never resolved — not since August but since the model was made
  in July; and until the address key was added on 26 August, username was the
  only parameter, so for five weeks no lockout worked at all.
  `AXES_USERNAME_FORM_FIELD = "username"` (PR #11) fixes it; a test with axes
  enabled asserts the row carries the email. `AXES_ENABLE_ACCESS_FAILURE_LOG`
  is on too (PR #13) — the admin's *Access failures* page had been empty
  because axes leaves that log off by default.

- **The palette has a true neutral** (2026-08-24). It had none: all 40 tints
  were colours, and the family at hue 360° was named "slate" while rendering a
  pink, which `DEFAULT_TINT` pointed at. That family is now `rose`, which is what
  it is, and a real neutral pair is generated outside the hue ring and is the new
  default. Migration `0019` renames stored values; the rename does not change the
  colour anything renders.

- **The `stage_rule` monkeypatch is gone** (`1b4f094`, 2026-08-24).
  `stage_rule()` and `weekly_rates()` take an optional `{stage: rule}` mapping
  instead. The same N+1 existed unfixed in the fill engine — three trainee
  passes each calling `weekly_rates()` per profile — and is fixed too. Guarded
  by query count rather than by mechanism.

- **The trainee report's "expected" column** shows requirements accruing from
  `requirements_tracked_from` (or placement start when blank), and that is what
  it should show — Tom, 2026-08-24. The system reports what it was asked to
  track; the placement's full contractual total is a deanery question, not a
  rota one. No change needed; `rota/views/reports.py:179` already does this.

## Open — minor

Parked by the account-access work (2026-09-04), none blocking:

- **Two login tabs can desync a passkey sign-in once.** The server keeps one
  challenge per session and the newest mint wins; the login page re-arms on
  tab focus so the visible tab holds it, but two tabs racing their arming
  requests can still make one attempt fail with "could not be verified" before
  a retry works. A per-challenge list server-side would close it.
- **`SESSION_COOKIE_AGE` is Django's two-week default**, so
  `rota-clearsessions.timer` reaps a login-page session row a fortnight after
  the passkey autofill minted it. A day or two would bound the table properly.
- **The passkey credential-id cap counts bytes (1023) while the column counts
  base64url characters (1024).** Harmless on SQLite, which ignores
  `max_length`; a `DataError` on Postgres. Cap at 768 bytes or widen the column
  if the database ever changes.
- **`last_used_at` on a passkey advances before the inactive-account check**,
  so the admin can show a last use for an account that never got in. The sign
  count advancing is correct (clone detection); the timestamp is cosmetic.
- **`exclude_credentials` omits the stored transports hint**, the one thing the
  `transports` column exists for in WebAuthn.
- **The card offering a passkey drops keyboard focus** on *Not now* and on
  success (the focused button is hidden or replaced); a focus handoff to the
  page would fix it.
- **Two near-simultaneous public reset requests could both send** — the
  five-minute throttle reads and writes the account's stamp without a row lock.
  Practice-scale; worst case is two emails to the same inbox.
- **`EMAIL_USE_TLS` honours only the literal `1`**, matching `DEBUG`'s parsing;
  `=true` would silently turn STARTTLS off. The README documents `=0` only.
- **The signed-in email in the header is now a link and carries the browser's
  default underline**; no CSS was added. A look call for Tom on staging.
- **The dashboard's query count scales with coverage rules and entries** (from
  the admin overhaul, PR #8); a windowed resolver in `day_warnings` is service
  work. Also from that branch: the colour-swatch radios carry no `id`; the
  ordered-checkbox widget hard-codes `max="7"`.

## Configuration notes

The three configuration problems previously recorded here — inverted
`counts_toward_entitlement`, unset leave entitlements, and missing pattern
slots — were read off the **development** database on this box, not the test
deployment. They do not describe the deployed system and have been removed.

Worth keeping as a lesson rather than a task: the dev DB and the deployed one
have diverged, so any future claim about "the data" needs to say which database
it came from.

## Decided — not defects, do not re-raise

Deliberate choices, recorded so they stop being re-reported by each review pass.

- **systemd units run as root.** Correct for this single-purpose LXC. Revisit
  only if the container ever hosts anything else.
- **Fill re-run has no preview step**, though the spec asks for previews on
  destructive actions. Accepted: re-run provably touches only its own unpublished
  drafts, never published or manually-set entries, and that is enforced by tests.
- **Swap audit log records one clinician's name per touched slot** (the other
  appears in the free-text detail). A second row per swap would be a tidier
  trail, but the information is not lost.
- **Only a superuser can set a password directly**, at
  `/admin/accounts/user/<id>/password/`, and nothing links to it. A rota admin
  sends links; nobody knows anyone's password. Tom, 2026-09-04.
- **`is_staff` is derived, not set.** It follows Admin status or superuser on
  save, because in this app it grants nothing except unfold's command palette
  and Django's own help text under the toggle claimed it controlled admin
  login. The toggle is gone from the form. Tom, 2026-09-04.
- **The link an admin is shown to copy is a clickable `<a>`**: on a phone a
  long-press offers *Copy link*, which is the point; clicking it lands on
  someone else's set-password page, which is visible and undone by logging
  out.
- **No console email backend for `DEBUG=1`.** Every send path returns before
  the backend when `EMAIL_HOST` is unset, so it could never fire, and it
  contradicted "`EMAIL_HOST` being set is what configured means". A dev box
  gets links on screen like production.
- **Passkeys are for personal devices; the shared-PC caution is documentation,
  not code.** Conditional UI offers every passkey enrolled on a machine to
  whoever focuses the email field; a shared Windows PIN shares the gate.
- **The `tests` check is strict**: a PR must be up to date with master to
  merge, so every landing invalidates the other open PRs' runs and they are
  rebased and re-run serially. Tom, 2026-09-04.
- **The draft hatch is a weak signal on its own.** Unpublished sessions carry a
  diagonal wash, deliberately subtle so the tint underneath stays readable, which
  means it reads as texture rather than as a WCAG 1.4.11 non-text cue. Acceptable
  while draft state is also carried by the "Publish week" button and the fill
  screen's own summary — worth revisiting if drafts ever appear without that
  surrounding context.

## Outstanding project work

- **Deployment — done, 2026-08-24**, running on the LXC behind the Cloudflare
  tunnel at `/home/rota-live/rota`. Tom uses it to test every branch before
  merging; **real GPs have not started using it day to day** as of 2026-09-04.
  Mailjet is configured there and sending.

- **Manual smoke test — in progress.** The first pass immediately found four
  issues: a template comment rendering to the page and an unfiltered trainer
  dropdown (both fixed in `580747e`), an assisted-fill run that produced nothing
  because the clinician patterns had not been populated yet, and a question about
  eligibility semantics that turned out to be working as intended. Later passes
  on staging found the sender-parse 500, the empty axes pages and the two
  passkey requests the autofill work needed. Still to do: configure the real
  practice rules, run a 4-week fill with patterns populated, and check the
  result against how the rota is actually built. Two admin data steps from
  the frontend work are still worth confirming on the staging database: give
  "Routine - PMC" its own code (two types both render as `Routine`), and tick
  **Pin on day view** on Duty or the day view's pinned block never appears.

- **Frontend Phase 1 — done** (`f82033c`, 2026-08-24): the design system on
  every screen, browser-verified. **Phase 2 — done** (PR #5, 2026-09-01): the
  day view at `/rota/day/`, My Schedule rebuilt for a phone, the tab bar below
  640px; installable to a home screen (2026-09-01), with a service worker
  deliberately deferred because offline caching of an authenticated rota is a
  decision for after living with standalone mode. **Phase 3 is specced and not
  started:** grid interaction — drag-and-drop assignment, keyboard navigation,
  inline editing.

- **Admin overhaul — done** (PR #8, 2026-09-04): django-unfold, the setup
  dashboard, the sidebar by job. Option C from its spec — bespoke guided flows
  such as a "New clinician" wizard — was deferred until a practice manager has
  used the plain admin.

- **Not tested on iOS.** Tom has no iOS device or simulator; the home-screen
  install, the safe-area inset and passkeys on Safari have been reasoned from
  the specs and verified on Android and Windows only.
