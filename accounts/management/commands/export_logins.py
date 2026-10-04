"""Every rota login, for the HR system's import_logins (docs/admin/sign-in.md,
"Migrating logins from the rota").

The file is a contract with that command: `exported_at`, then one entry per
login — `email`, `password`, `is_active`, `is_rota_admin`, `is_superuser` —
for every account, inactive ones and superusers included. `password` is the
hash exactly as stored (`!…` for an account with no usable password), so
the HR system can take it over without anyone choosing a new one.

Hashes are secrets, so the file is created owner-only and never written over
an existing one, and nothing about any login is printed: only how many were
written, and where."""

import json
import os

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User


class Command(BaseCommand):
    help = "Write every login account to a new owner-only JSON file for the HR system's import."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Where to write it; must not exist.")

    def handle(self, *args, **options):
        path = options["file"]
        logins = [
            {"email": u.email, "password": u.password, "is_active": u.is_active,
             "is_rota_admin": u.is_rota_admin, "is_superuser": u.is_superuser}
            for u in User.objects.order_by("email")
        ]
        data = json.dumps({"exported_at": timezone.now().isoformat(), "logins": logins},
                          indent=2) + "\n"
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise CommandError(f"{path} already exists; export_logins never overwrites a file.")
        except OSError as exc:
            raise CommandError(f"Cannot create {path}: {exc.strerror}.")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        noun = "login" if len(logins) == 1 else "logins"
        self.stdout.write(f"Wrote {len(logins)} {noun} to {path}.")
