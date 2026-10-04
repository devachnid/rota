"""export_logins: every rota login, as the HR system's import_logins reads it.

The file carries password hashes, so it is made owner-only, never written
over an existing file, and the command says nothing on screen but a count
and where the file is."""

import json
import os
import stat
from datetime import datetime
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

User = get_user_model()


def _run(path):
    out, err = StringIO(), StringIO()
    call_command("export_logins", "--file", str(path), stdout=out, stderr=err)
    return out.getvalue() + err.getvalue()


@pytest.fixture
def logins(db):
    gp = User.objects.create_user(email="gp@example.org", password="pw")
    boss = User.objects.create_user(email="boss@example.org", password="pw", is_rota_admin=True)
    gone = User.objects.create_user(email="gone@example.org", password="pw", is_active=False)
    new = User.objects.create_user(email="new@example.org")     # invited, never set up
    root = User.objects.create_superuser(email="root@example.org", password="pw")
    return gp, boss, gone, new, root


def test_the_file_is_the_shape_the_hr_import_reads(logins, tmp_path):
    gp, boss, gone, new, root = logins
    path = tmp_path / "logins.json"
    _run(path)
    data = json.loads(path.read_text())
    assert list(data) == ["exported_at", "logins"]
    assert datetime.fromisoformat(data["exported_at"]).tzinfo is not None
    by_email = {row["email"]: row for row in data["logins"]}
    assert set(by_email) == {u.email for u in logins}
    for row in data["logins"]:
        assert list(row) == ["email", "password", "is_active", "is_rota_admin", "is_superuser"]
    assert by_email["gp@example.org"] == {
        "email": "gp@example.org", "password": gp.password,
        "is_active": True, "is_rota_admin": False, "is_superuser": False}
    assert by_email["boss@example.org"]["is_rota_admin"] is True
    assert by_email["gone@example.org"]["is_active"] is False
    assert by_email["root@example.org"]["is_superuser"] is True
    # Unusable, exactly as stored: the import sets no password from it.
    assert by_email["new@example.org"]["password"] == new.password
    assert new.password.startswith("!")


def test_the_file_is_owner_only(logins, tmp_path):
    path = tmp_path / "logins.json"
    _run(path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_an_existing_file_is_never_overwritten(logins, tmp_path):
    path = tmp_path / "logins.json"
    path.write_text("keep me")
    with pytest.raises(CommandError, match="already exists"):
        _run(path)
    assert path.read_text() == "keep me"


def test_only_the_count_and_the_path_are_printed(logins, tmp_path):
    path = tmp_path / "logins.json"
    out = _run(path)
    assert out.strip() == f"Wrote 5 logins to {path}."
    for user in logins:
        assert user.password not in out


def test_a_login_with_no_hash_at_all_is_written_unusable(db, tmp_path):
    """The HR import refuses an empty or unrecognisable password, and would
    abort the whole file over one. Such a login has no password to carry
    across, so it goes as unusable; real hashes go exactly as stored."""
    from django.contrib.auth.hashers import is_password_usable
    real = User.objects.create_user(email="real@example.org", password="pw")
    for email, stored in (("empty@example.org", ""), ("odd@example.org", "not-a-hash")):
        User.objects.filter(pk=User.objects.create_user(email=email).pk).update(password=stored)
    path = tmp_path / "logins.json"
    _run(path)
    by_email = {r["email"]: r["password"] for r in json.loads(path.read_text())["logins"]}
    assert by_email["real@example.org"] == real.password
    for email in ("empty@example.org", "odd@example.org"):
        assert by_email[email].startswith("!") and len(by_email[email]) > 1
        assert not is_password_usable(by_email[email])


def test_a_failed_write_leaves_no_partial_file(logins, tmp_path, monkeypatch):
    from accounts.management.commands import export_logins

    real_fdopen = os.fdopen

    class Full:
        def __init__(self, f):
            self.f = f

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.f.close()

        def write(self, data):
            self.f.write(data[:10])
            self.f.flush()
            raise OSError(28, "No space left on device")

    monkeypatch.setattr(export_logins.os, "fdopen", lambda *a, **k: Full(real_fdopen(*a, **k)))
    path = tmp_path / "logins.json"
    with pytest.raises(OSError):
        _run(path)
    assert not path.exists()
