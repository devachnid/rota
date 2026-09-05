# GP Rota

Session-based GP practice rota. The design specs live in
`docs/superpowers/specs/`, one per piece of work in the order it was built: v1;
autofill v2 (trainees, commitments, demand-driven clinics, PMC branch cover);
the frontend's first phase; the post-deployment fixes; the frontend's second
phase (mobile); leave from Breathe; the admin overhaul; the grid and locum
enhancements; and account access — invitations, self-service passwords,
passkeys. The implementation plans are in `docs/superpowers/plans/`.

## Develop

    source .venv/bin/activate
    DEBUG=1 python manage.py migrate
    DEBUG=1 python manage.py runserver
    pytest

`DEBUG=1` is what lets `manage.py` start on a box with no `SECRET_KEY` in the
environment: with debug off, the settings refuse to run on the repository's
placeholder key (see Deploy). The suite needs neither — it detects pytest.
With no `EMAIL_HOST` set, a dev box behaves as production does without a relay:
the admin is shown each invitation link on screen instead of it being sent.

CI (`.github/workflows/tests.yml`) runs `ruff check .` (pyflakes only — see
`ruff.toml`), `makemigrations --check`, the suite, and `collectstatic` +
`check --deploy` against a throwaway environment; the master ruleset requires
it green and up to date. Locally: `pip install ruff==0.16.6 && ruff check .`.

## Admin guide

Every admin setting is documented in [docs/admin/](docs/admin/README.md) — one
page per area, each field explained with what depends on it and what goes wrong
if it is set wrong. The sequence below gets a new practice running; that guide
is the reference for what the settings actually mean.

## First-time setup

1. `python manage.py createsuperuser`
2. Sign in and open **Admin**. The dashboard's **Setup** card lists nine
   steps, each detected from the database (or, for outgoing email, the
   environment) and linked to where it is done in the admin;
   follow it until it reads "Setup complete". The **Health** card beside it
   is what to glance at afterwards.
3. Create everyone's login accounts under **People › Login accounts › Add** —
   an email and whether they are an admin, nothing else. Each person receives
   an invitation, chooses their own password from its link, and can then add a
   passkey. The superuser's from step 1 is the only password an admin ever
   types. See [Login accounts](docs/admin/people.md#login-accounts).

The sequence the checklist walks, for reference: practice settings → sites →
clinician groups → session types → coverage rules → clinicians → working
patterns → Breathe → outgoing email. Trainees, recurring commitments and locum bookings are
day-to-day work, not setup — see [docs/admin/](docs/admin/README.md).

## Deploy (LXC + Cloudflare tunnel)

    pip install -r requirements.txt

Create the secrets file first — root-only, never in the unit file:

    umask 077
    .venv/bin/python -c 'from django.core.management.utils import get_random_secret_key as k; print("SECRET_KEY=" + k())' > /etc/rota.env
    cat >> /etc/rota.env <<'EOF'
    DEBUG=0
    ALLOWED_HOSTS=rota.example.org
    CSRF_TRUSTED_ORIGINS=https://rota.example.org
    EOF
    chmod 600 /etc/rota.env

Then:

    set -a; . /etc/rota.env; set +a
    python manage.py collectstatic --noinput
    python manage.py migrate
    cp deploy/gunicorn.service /etc/systemd/system/rota.service
    cp deploy/rota-backup.* deploy/rota-clearsessions.* deploy/rota-breathe.* /etc/systemd/system/
    systemctl daemon-reload && systemctl enable --now rota rota-backup.timer rota-clearsessions.timer

`rota-breathe.timer` is enabled later, once every clinician is linked — step 5
of [Leave from Breathe](docs/admin/breathe.md#setting-it-up-in-this-order).

Point the Cloudflare tunnel ingress at `http://127.0.0.1:8321`.
Backups land in `backups/`, kept 30 days. Expired sessions are cleared
nightly by `rota-clearsessions.timer`: the login page's passkey autofill
mints a session per visit, so the table would otherwise only grow.

### Outgoing email

Invitations and password-reset links go by email, and so do the two feedback
emails: a note to every active superuser when someone sends a bug report or
idea from the app, and an admin's reply to the reporter. Without a relay the
app still works — an admin is shown each password link to copy into an email,
feedback still lands in the admin, and the dashboard's *Outgoing email* step
and `manage.py check --deploy` both say so. All of it uses the same `EMAIL_*`
keys below and nothing more.

Mailjet is plain authenticated SMTP. In Mailjet: validate the sender (the
whole domain, adding the SPF and DKIM records it gives you in Cloudflare
DNS), create an API key, and under account settings turn **click tracking**
and **open tracking** off — the app also asks for that on every message,
but a rewritten link is the one thing that must not happen to a password
link. Then:

    cat >> /etc/rota.env <<'EOF'
    EMAIL_HOST=in-v3.mailjet.com
    EMAIL_PORT=587
    EMAIL_HOST_USER=MAILJET_API_KEY_HERE
    EMAIL_HOST_PASSWORD=MAILJET_SECRET_KEY_HERE
    DEFAULT_FROM_EMAIL="Practice Rota <rota@rota.example.org>"
    EOF
    systemctl restart rota

The quotes matter: the file is sourced by a shell as well as read by
systemd, and an unquoted `<` is a redirection. No trailing comments — an
env file has no comment syntax after a value.
A display name containing an `@`, a comma or other punctuation must itself
be quoted or Django cannot parse the sender — write
`DEFAULT_FROM_EMAIL='"Rota @ Practice" <rota@example.org>'` — or keep it
to plain words. `manage.py check --deploy` says so (`rota.E005`).

`EMAIL_USE_TLS` defaults on (STARTTLS on 587); set `EMAIL_USE_TLS=0` only for a
relay that has no TLS at all. Links last seven days. With no `EMAIL_HOST`, a
dev box behaves exactly like production: the admin gets each link on screen.

### Passkeys and the domain

People add passkeys from their **Account** page or from the card offered after
a password sign-in, and on the login page a passkey enrolled on that device is
offered in the email field's autofill — see [Login
accounts](docs/admin/people.md#signing-in-and-lockouts). Passkeys are bound to
the host the app is served from (`ALLOWED_HOSTS`, the tunnel's hostname).
Changing that domain invalidates every passkey — people sign in with their
password and enrol again. The origin the browser signs must be `https://`, so
cloudflared has to pass `X-Forwarded-Proto` — it does by default; the
`Strict-Transport-Security` header in the debug check below is proof, because
Django only emits it when it believes the request is secure. `js/passkeys.js`
must be collected (`collectstatic` is in every redeploy).

### Redeploying

**`collectstatic` is not optional on a redeploy.** With `DEBUG=0` every
`{% static %}` resolves through a manifest that `collectstatic` writes, so
pulling code that references a new asset — a font, a stylesheet — without
rebuilding the manifest makes *every page* return 500, with the traceback
going only to the journal. That has happened.

    set -a; . /etc/rota.env; set +a
    git pull
    pip install -r requirements.txt
    python manage.py migrate
    python manage.py collectstatic --noinput
    python manage.py check --deploy   # fails loudly if the manifest is stale
    systemctl restart rota

`check --deploy` verifies that every asset the templates reference is in the
manifest, and that every stored weekday and month list still parses (`rota.E006`
names the record to open and save if not), so run it before the restart rather
than after. It has to be
`--deploy` rather than plain `check`: an ordinary check would also run during
`collectstatic` and `migrate`, which legitimately run before a manifest
exists.

### Login rate limiting behind the tunnel

axes locks out by username **and** by client address. The address comes from
Cloudflare's `CF-Connecting-IP`, believed only when the request arrives from
`TRUSTED_PROXY_IPS` (loopback by default, where cloudflared connects) — see
`accounts/client_ip.py` for why it is that header and not `X-Forwarded-For`.

A password lockout does not block signing in with a passkey: a passkey proves
possession of the device, which is the stronger claim. A forged passkey
assertion for a registered passkey counts against the address and the account
like a wrong password does.

The record is in the admin's **System** group, for superusers: **Access
failures** is the log of failed attempts (the last thousand per email); **Access attempts** is
the live counter, and is cleared for an address as soon as anyone there logs in
successfully (that is what keeps a shared surgery connection from locking the
building out); **Access logs** records successful sign-ins.

Nothing to configure for a standard tunnel. **Do verify the header actually
arrives**, because if it does not, every attempt is recorded as `127.0.0.1`
and address-based lockout quietly stops meaning anything:

    python manage.py shell -c "from axes.models import AccessAttempt; print(list(AccessAttempt.objects.values_list('ip_address', 'username')[:5]))"

Fail a login once from outside, then run that. Real client addresses mean it
is working; `127.0.0.1` means the header is being stripped somewhere and only
username keying is live.

If gunicorn is ever put behind something other than cloudflared, set
`TRUSTED_PROXY_IPS` in `/etc/rota.env` to that proxy's address — and never to
`0.0.0.0` or a wildcard, which would let any client name its own address.

**Check the deployment is not in debug mode.** `DEBUG` defaults to off, but a
stray `DEBUG=1` turns on tracebacks, publishes the URL map on every 404, and
drops HSTS and the `Secure` cookie flags. Two commands tell you:

    curl -sI https://your-host/accounts/login/ | grep -i 'strict-transport\|set-cookie'
    curl -s https://your-host/no-such-path/ | grep -c 'Django tried these URL patterns'

The first must show `Strict-Transport-Security` and a `csrftoken` cookie marked
`Secure`; the second must print `0`.

### Appendix: the setup steps in detail

Step 1 is `createsuperuser`, above. The rest, in the order the dashboard walks them:

2. Create clinician groups (e.g. Partner, Salaried, GPST, and a Locum group
   with "is locum group" ticked). Set display order and any per-session minimums.
3. Create session types: Duty (fairness tracked), Routine, Visits, Admin, CPD,
   Annual leave (absence), Study leave, Sick (absence).
4. Create a coverage rule: Duty, per full day, count 1, priority 1.
5. Create clinicians and their pattern slots, and link each to their login
   account (People › Login accounts › Add sends the invitation).
6. In Practice settings: minimum clinical GPs per session, default fill
   session type (Routine), open weekdays.
7. Add closed days (bank holidays) as they come.
8. Link each clinician to their Breathe employee — see
   docs/admin/breathe.md.
9. Set up outgoing email so invitations and password resets are sent — see
   Deploy › Outgoing email. Until then the admin copies each link by hand.

#### v2: trainees, commitments, and demand-driven clinics

10. Mark trainers: tick `is_trainer` on any Clinician who can supervise a
    mentoring session (Clinician admin).
11. Create a trainee profile for each trainee: on the Clinician admin page,
    fill in the inline TraineeProfile — stage (FY2/ST1/ST2/ST3), WTE percent,
    trainer (optional; leave blank to always substitute), placement start/end.
    If the trainee's placement is already in progress, also set
    `requirements_tracked_from` to the date the rota system starts tracking
    them. Left blank, accrual anchors at `placement_start` and the engine
    treats every week since then as owed — for a trainee already partway
    through their placement, that shows up as a large phantom backlog.
12. Review the seeded TraineeStageRule table (one row per stage, editable):
    FY2 defaults to 0 VTS / 2 SDL / 1 mentoring per week (no anchored VTS
    day); ST1/ST2/ST3 default to 1 VTS / 1 SDL / 1 mentoring per week, VTS
    anchored to Tuesday AM (ST1/ST2) or Tuesday PM (ST3). Rates scale by the
    trainee's WTE percent; adjust the seeds if your deanery's entitlement
    differs.
13. In Practice settings, point `vts_session_type`, `sdl_session_type`, and
    `mentoring_session_type` at the relevant SessionTypes (create them first,
    category Non-clinical, if they don't already exist). Leaving any of the
    three blank simply skips that trainee pass — no error.
14. Add RecurringCommitments for fixed personal fixtures (e.g. a GP's weekly
    Vision clinic): clinician, session type, weekday, part (AM/PM/full day),
    optional site, `active_from` (and optional `active_until`), and
    `interval_weeks` (1 = weekly, 2 = fortnightly, anchored to the week of
    `active_from`). The commitments pass runs first and never overwrites an
    existing entry.
15. New CoverageRule shapes, beyond the original per-slot/per-day rule:
    - **Vas Clinic** (demand-driven, full day preferred): frequency
      `PER_WEEK`, count `2`, unit `FULL_DAY_PREFERRED`, `preferred_weekdays`
      `3,1` (Thursday then Tuesday, Monday=0) — tries one clinician across
      both AM+PM on the preferred day first, falling back to separate AM/PM
      sessions (still preferred-day-first) if no one is free for the whole
      day.
    - **Coil Clinic** (demand-driven, monthly average): frequency
      `PER_MONTH`, count `2` — placed by weekly-rate accrual so the pool
      averages 2 sessions/month rather than a rigid per-week amount.
    - **PMC branch cover, winter/summer pair**: two CoverageRule rows on
      the same PMC-Routine session type — `PER_SLOT`/`PER_DAY`, `months`
      `10,11,12,1,2,3,4` (winter, all day) and `PER_SLOT`/`PER_SESSION`,
      `parts` `AM`, `months` `5,6,7,8,9` (summer, AM only). `applies_on()`
      checks both the weekday list and the month list, so the two rules
      never overlap.
    - **PMC-Routine blocking Duty**: on the PMC-Routine SessionType, add
      `Duty` to `blocks_same_day` — a clinician holding PMC-Routine that day
      is then excluded from Duty auto-assignment the same day (the "no duty
      on your PMC PM" rule, summer's free PM included). `blocks_same_day` is
      evaluated at placement time and is directional (it only bites when the
      BLOCKING type — PMC-Routine here — fills first), so give the
      PMC-Routine CoverageRule(s) a **lower** priority number than Duty's;
      if Duty fills first the block never fires.
    - **Minor Ops** (demand-driven, monthly average): frequency `PER_MONTH`,
      count `1` — same shape as Coil Clinic, placed by weekly-rate accrual.
    - Give Vas/Coil/Minor-Ops session types `fairness_tracked=True` for even
      pool-scoped sharing; leave PMC types untracked so they use simple
      longest-since rotation instead. Fairness pooling is scoped by who is
      *eligible* for the type, so you must also define the pool: set
      `allowed_clinicians` on Vas/Coil/Minor-Ops to the clinicians with
      those skills, and set `allowed_groups` = Partner + Salaried on the PMC
      types (leaving trainees and PAs excluded). A session type with neither
      `allowed_clinicians` nor `allowed_groups` set is open to everyone.
    - Set `default_site` on PMC session types so placements auto-stamp the
      branch site.
