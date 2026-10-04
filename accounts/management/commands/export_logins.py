"""Every rota login, for the HR system's import_logins (docs/admin/sign-in.md,
"Moving the rota's logins to the HR system").

The file is a contract with that command: `exported_at`, then one entry per
login — `email`, `password`, `is_active`, `is_rota_admin`, `is_superuser` —
for every account, inactive ones and superusers included. `password` is the
hash exactly as stored, so the HR system can take it over without anyone
choosing a new one, or `!…` for an account with no usable password. A
stored value that is no hash at all (empty, say) goes as `!…` too: the
import refuses anything else, and would abort the whole file over it.

Hashes are secrets, so the file is created owner-only and never written over
an existing one, and nothing about any login is printed: only how many were
written, and where."""

import json
import os

from django.contrib.auth.hashers import (UNUSABLE_PASSWORD_PREFIX, identify_hasher,
                                         make_password)
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User


def _exported(encoded):
    """The stored hash, or a fresh unusable marker for anything that is not
    one."""
    if encoded.startswith(UNUSABLE_PASSWORD_PREFIX):
        return encoded
    try:
        identify_hasher(encoded)
    except ValueError:
        return make_password(None)
    return encoded


class Command(BaseCommand):
    help = "Write every login account to a new owner-only JSON file for the HR system's import."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Where to write it; must not exist.")

    def handle(self, *args, **options):
        path = options["file"]
        logins = [
            {"email": u.email, "password": _exported(u.password), "is_active": u.is_active,
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
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
        except BaseException:
            # A half-written file would be refused by the import, and would
            # block the next run here (it never overwrites).
            os.unlink(path)
            raise
        noun = "login" if len(logins) == 1 else "logins"
        self.stdout.write(f"Wrote {len(logins)} {noun} to {path}.")
