# GP Rota

Session-based GP practice rota. Spec: `docs/superpowers/specs/2026-07-18-gp-rota-design.md`
(v1) and `docs/superpowers/specs/2026-08-22-autofill-v2-design.md` (trainees,
commitments, demand-driven clinics, PMC branch cover).

## Develop

    source .venv/bin/activate
    python manage.py migrate && python manage.py runserver
    pytest

## Admin guide

Every admin setting is documented in [docs/admin/](docs/admin/README.md) — one
page per area, each field explained with what depends on it and what goes wrong
if it is set wrong. The sequence below gets a new practice running; that guide
is the reference for what the settings actually mean.

## First-time setup (via /admin/)

1. `python manage.py createsuperuser`
2. Create clinician groups (e.g. Partner, Salaried, GPST, and a Locum group
   with "is locum group" ticked). Set display order and any per-session minimums.
3. Create session types: Duty (fairness tracked), Routine, Visits, Admin, CPD,
   Annual leave (absence, counts toward entitlement), Study leave, Sick (absence).
4. Create a coverage rule: Duty, per full day, count 1, priority 1.
5. Create clinicians (link user accounts) and their pattern slots.
6. In Practice settings: minimum clinical GPs per session, leave year start,
   default fill session type (Routine), open weekdays.
7. Add closed days (bank holidays) as they come.

### v2: trainees, commitments, and demand-driven clinics

8. Mark trainers: tick `is_trainer` on any Clinician who can supervise a
   mentoring session (Clinician admin).
9. Create a trainee profile for each trainee: on the Clinician admin page,
   fill in the inline TraineeProfile — stage (FY2/ST1/ST2/ST3), WTE percent,
   trainer (optional; leave blank to always substitute), placement start/end.
   If the trainee's placement is already in progress, also set
   `requirements_tracked_from` to the date the rota system starts tracking
   them. Left blank, accrual anchors at `placement_start` and the engine
   treats every week since then as owed — for a trainee already partway
   through their placement, that shows up as a large phantom backlog.
10. Review the seeded TraineeStageRule table (one row per stage, editable):
    FY2 defaults to 0 VTS / 2 SDL / 1 mentoring per week (no anchored VTS
    day); ST1/ST2/ST3 default to 1 VTS / 1 SDL / 1 mentoring per week, VTS
    anchored to Tuesday AM (ST1/ST2) or Tuesday PM (ST3). Rates scale by the
    trainee's WTE percent; adjust the seeds if your deanery's entitlement
    differs.
11. In Practice settings, point `vts_session_type`, `sdl_session_type`, and
    `mentoring_session_type` at the relevant SessionTypes (create them first,
    category Non-clinical, if they don't already exist). Leaving any of the
    three blank simply skips that trainee pass — no error.
12. Add RecurringCommitments for fixed personal fixtures (e.g. a GP's weekly
    Vision clinic): clinician, session type, weekday, part (AM/PM/full day),
    optional site, `active_from` (and optional `active_until`), and
    `interval_weeks` (1 = weekly, 2 = fortnightly, anchored to the week of
    `active_from`). The commitments pass runs first and never overwrites an
    existing entry.
13. New CoverageRule shapes, beyond the original per-slot/per-day rule:
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
    cp deploy/rota-backup.* /etc/systemd/system/
    systemctl daemon-reload && systemctl enable --now rota rota-backup.timer

Point the Cloudflare tunnel ingress at `http://127.0.0.1:8321`.
Backups land in `backups/`, kept 30 days.

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
    python manage.py check            # fails loudly if the manifest is stale
    systemctl restart rota

`manage.py check` verifies that every asset the templates reference is in the
manifest, so run it before the restart rather than after.

**Check the deployment is not in debug mode.** `DEBUG` defaults to off, but a
stray `DEBUG=1` turns on tracebacks, publishes the URL map on every 404, and
drops HSTS and the `Secure` cookie flags. Two commands tell you:

    curl -sI https://your-host/accounts/login/ | grep -i 'strict-transport\|set-cookie'
    curl -s https://your-host/no-such-path/ | grep -c 'Django tried these URL patterns'

The first must show `Strict-Transport-Security` and a `csrftoken` cookie marked
`Secure`; the second must print `0`.
