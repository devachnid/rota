"""The systemd units, the backup script and the manage wrapper: the app runs
as its own user in a sandbox, never as root.

These read the files in deploy/ rather than a running system, so they pin
what a fresh install or a redeploy copies into /etc/systemd/system. That the
directives work in the practice's LXC was checked by running the units there;
see the README's Deploy section.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
SERVICES = sorted(DEPLOY.glob("*.service"))

SANDBOX = {
    "NoNewPrivileges": "yes",
    "ProtectSystem": "strict",
    "ProtectHome": "yes",
    "PrivateTmp": "yes",
    "PrivateDevices": "yes",
    "ProtectKernelTunables": "yes",
    "ProtectKernelModules": "yes",
    "ProtectKernelLogs": "yes",
    "ProtectControlGroups": "yes",
    "ProtectClock": "yes",
    "ProtectHostname": "yes",
    "ProtectProc": "invisible",
    "ProcSubset": "pid",
    "RestrictNamespaces": "yes",
    "RestrictSUIDSGID": "yes",
    "RestrictRealtime": "yes",
    "LockPersonality": "yes",
    "CapabilityBoundingSet": "",
    "RestrictAddressFamilies": "AF_INET AF_INET6 AF_UNIX",
    "SystemCallArchitectures": "native",
    "SystemCallFilter": "@system-service",
    "SystemCallErrorNumber": "EPERM",
}


def _directives(path):
    """{key: [values]} for the [Service] section, comments skipped."""
    out, section = {}, None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            section = line
            continue
        if section == "[Service]" and "=" in line:
            key, value = line.split("=", 1)
            out.setdefault(key, []).append(value)
    return out


def test_there_are_five_services():
    assert [p.name for p in SERVICES] == [
        "gunicorn.service", "rota-backup.service",
        "rota-breathe.service", "rota-clearsessions.service",
        "rota-pbs.service"]


@pytest.mark.parametrize("unit", SERVICES, ids=lambda p: p.name)
def test_every_service_runs_as_the_rota_user(unit):
    d = _directives(unit)
    assert d.get("User") == ["rota"], "a missing User= means root"
    assert d.get("Group") == ["rota"]


@pytest.mark.parametrize("unit", SERVICES, ids=lambda p: p.name)
def test_every_service_keeps_its_data_in_the_closed_state_directory(unit):
    d = _directives(unit)
    assert d.get("StateDirectory") == ["rota"]
    assert d.get("StateDirectoryMode") == ["0700"]
    assert d.get("UMask") == ["0077"], "files the app writes are nobody else's"


@pytest.mark.parametrize("unit", SERVICES, ids=lambda p: p.name)
def test_every_service_carries_the_whole_sandbox(unit):
    d = _directives(unit)
    wrong = {k: d.get(k) for k, v in SANDBOX.items() if d.get(k) != [v]}
    assert not wrong, f"{unit.name}: sandbox directives missing or different: {wrong}"


@pytest.mark.parametrize("unit", SERVICES, ids=lambda p: p.name)
def test_no_service_reaches_into_root_home(unit):
    """/root is where the app used to live. ProtectHome=yes hides it, so a
    path there would fail at start, and pointing back there is the regression
    this change removes."""
    live = [ln for ln in unit.read_text().splitlines()
            if ln.strip() and not ln.lstrip().startswith(("#", ";"))]
    assert not [ln for ln in live if "/root" in ln]


@pytest.mark.parametrize("unit", SERVICES, ids=lambda p: p.name)
def test_the_code_runs_from_srv(unit):
    d = _directives(unit)
    for cmd in d["ExecStart"]:
        assert cmd.startswith("/srv/rota/"), cmd
    if unit.name not in ("rota-backup.service", "rota-pbs.service"):
        assert d.get("WorkingDirectory") == ["/srv/rota"]
        assert d.get("EnvironmentFile") == ["/etc/rota.env"]


def test_gunicorn_listens_on_loopback_only():
    (cmd,) = _directives(DEPLOY / "gunicorn.service")["ExecStart"]
    assert "--bind 127.0.0.1:8321" in cmd


def test_the_env_file_comment_sets_the_database_path():
    """A fresh install that copies the comment gets a database in the state
    directory, not in the root-owned, read-only code tree."""
    assert "DB_PATH=/var/lib/rota/db.sqlite3" in (DEPLOY / "gunicorn.service").read_text()


# --- backup.sh -----------------------------------------------------------------

def test_backups_are_written_private_into_the_state_directory():
    script = (DEPLOY / "backup.sh").read_text()
    assert re.search(r"^umask 077$", script, re.M)
    assert "STATE_DIRECTORY" in script
    assert "/root" not in script


def test_the_backup_script_runs_and_keeps_its_copies_private(tmp_path):
    """Against a real SQLite file, with STATE_DIRECTORY as systemd sets it."""
    import sqlite3
    db = tmp_path / "db.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("create table t (x)")
    env = {**os.environ, "STATE_DIRECTORY": str(tmp_path)}
    try:
        subprocess.run(["sh", str(DEPLOY / "backup.sh")], env=env, check=True,
                       capture_output=True)
    except FileNotFoundError:
        pytest.skip("no sh")
    except subprocess.CalledProcessError as exc:
        if b"sqlite3: not found" in exc.stderr or b"sqlite3: command not found" in exc.stderr:
            pytest.skip("sqlite3 CLI not installed")
        raise
    (copy,) = (tmp_path / "backups").glob("db-*.sqlite3")
    assert copy.stat().st_mode & 0o077 == 0, oct(copy.stat().st_mode)
    assert (tmp_path / "backups").stat().st_mode & 0o077 == 0


# --- off-site backup to the Proxmox Backup Server --------------------------------

def test_the_pbs_secrets_stay_out_of_the_app_users_reach():
    """The token comes from a root-read env file and the encryption key as a
    credential, so the rota user (and the web process) never reads either."""
    d = _directives(DEPLOY / "rota-pbs.service")
    assert d.get("EnvironmentFile") == ["/etc/pbs-backup/rota.env"]
    assert d.get("LoadCredential") == ["pbs.key:/etc/pbs-backup/rota.key"]
    assert d.get("ExecStart") == ["/srv/rota/deploy/pbs-push.sh"]


def test_the_pbs_push_script_is_executable_and_valid_shell():
    script = DEPLOY / "pbs-push.sh"
    assert os.access(script, os.X_OK)
    try:
        subprocess.run(["sh", "-n", str(script)], check=True, capture_output=True)
    except FileNotFoundError:
        pytest.skip("no sh")


def test_the_pbs_push_script_sends_the_copies_encrypted_to_its_own_namespace():
    text = (DEPLOY / "pbs-push.sh").read_text()
    live = " ".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "$state/backups" in live, "the finished copies, not the live database"
    assert "db.sqlite3" not in live
    assert "--ns rota" in live and "--keyfile" in live
    assert "PBS_PASSWORD" not in text, "the token belongs in the root-only env file"


def test_the_pbs_dropin_runs_the_push_after_a_successful_backup():
    live = [ln for ln in (DEPLOY / "rota-backup-pbs.conf").read_text().splitlines()
            if ln.strip() and not ln.startswith("#")]
    assert live == ["[Unit]", "OnSuccess=rota-pbs.service"]


# --- deploy/manage -------------------------------------------------------------

def test_the_manage_wrapper_is_executable():
    assert os.access(DEPLOY / "manage", os.X_OK)
    assert os.access(DEPLOY / "backup.sh", os.X_OK)


def test_the_wrapper_lets_systemd_read_the_settings_and_drops_to_rota():
    script = (DEPLOY / "manage").read_text()
    assert "-p EnvironmentFile=/etc/rota.env" in script
    assert "--uid=rota --gid=rota" in script
    assert "UMask=0077" in script
    # It must not source the file: Django's generated keys hold ( and $.
    assert not re.search(r"^\s*\.\s+/etc/rota\.env", script, re.M)


def test_collectstatic_stays_root_and_world_readable():
    """staticfiles/ is in the root-owned code tree and WhiteNoise, as rota,
    must read what it writes."""
    script = (DEPLOY / "manage").read_text()
    start = script.index("= collectstatic ]")
    branch = script[start:script.index("\nelse\n", start)]
    assert "UMask=0022" in branch and "--uid" not in branch


@pytest.mark.skipif(os.geteuid() == 0, reason="the refusal is for non-root callers")
def test_the_wrapper_refuses_to_run_without_root():
    r = subprocess.run(["sh", str(DEPLOY / "manage"), "check"],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "run as root" in r.stderr


# --- settings ------------------------------------------------------------------

def _database_name(extra_env):
    env = {k: v for k, v in os.environ.items() if k != "DB_PATH"}
    env.update({"DEBUG": "1", "DJANGO_SETTINGS_MODULE": "config.settings", **extra_env})
    return subprocess.run(
        [sys.executable, "-c",
         "import django; django.setup(); from django.conf import settings; "
         "print(settings.DATABASES['default']['NAME'])"],
        env=env, cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()


def test_db_path_moves_the_database():
    assert _database_name({"DB_PATH": "/var/lib/rota/db.sqlite3"}) == "/var/lib/rota/db.sqlite3"


def test_without_db_path_the_database_sits_beside_manage_py():
    assert _database_name({}) == str(ROOT / "db.sqlite3")


# --- the docs --------------------------------------------------------------------

def _command_lines(text):
    """Lines a reader would paste: indented code and fenced code."""
    fenced = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if fenced or line.startswith("    "):
            yield line.strip()


def test_no_doc_runs_manage_py_on_the_server_by_hand():
    """On the server every command goes through deploy/manage; a dev box
    says DEBUG=1. Anything else is a root python opening a WAL database."""
    docs = [ROOT / "README.md", *sorted((ROOT / "docs" / "admin").glob("*.md"))]
    bad = [
        f"{doc.name}: {line}"
        for doc in docs for line in _command_lines(doc.read_text())
        if "manage.py" in line and not line.startswith("DEBUG=1")
    ]
    assert not bad, bad


def test_no_doc_sources_the_env_file_into_a_shell():
    docs = [ROOT / "README.md", *sorted((ROOT / "docs" / "admin").glob("*.md"))]
    bad = [
        f"{doc.name}: {line}"
        for doc in docs for line in _command_lines(doc.read_text())
        if re.search(r"(^|[;&]\s*)\.\s+/etc/rota\.env", line)
    ]
    assert not bad, bad
