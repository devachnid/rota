# GP Rota

Session-based GP practice rota. Spec: `docs/superpowers/specs/2026-07-18-gp-rota-design.md`.

## Develop

    source .venv/bin/activate
    python manage.py migrate && python manage.py runserver
    pytest

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

## Deploy (LXC + Cloudflare tunnel)

    pip install -r requirements.txt
    DEBUG=0 SECRET_KEY=... python manage.py collectstatic --noinput
    cp deploy/gunicorn.service /etc/systemd/system/rota.service   # edit env vars first
    cp deploy/rota-backup.* /etc/systemd/system/
    systemctl daemon-reload && systemctl enable --now rota rota-backup.timer

Point the Cloudflare tunnel ingress at `http://127.0.0.1:8321`.
Backups land in `backups/`, kept 30 days.
