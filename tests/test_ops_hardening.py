"""The low-risk items from the 2026-09-27 security review: an HTTPS redirect
of the app's own, no published development key, a request log that keeps
password links out of it, security events that reach the journal, and a
Breathe key that cannot leak through an error message."""

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.test import Client

ROOT = Path(__file__).resolve().parents[1]
TUNNEL = "127.0.0.1"


def _settings_value(expr, env):
    """A setting as a production process sees it: a fresh interpreter that is
    not running pytest, so config/settings.py's _TESTING is false."""
    base = {k: v for k, v in os.environ.items()
            if k not in ("DEBUG", "SECRET_KEY", "DB_PATH", "BREATHE_API_KEY")}
    base.update({"DJANGO_SETTINGS_MODULE": "config.settings", **env})
    return subprocess.run(
        [sys.executable, "-c", f"from config import settings as s; print(repr({expr}))"],
        env=base, cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()


# --- settings ---------------------------------------------------------------------

def test_production_redirects_http_to_https_itself():
    """Not left to the Cloudflare zone's "Always Use HTTPS" alone."""
    assert _settings_value("s.SECURE_SSL_REDIRECT",
                           {"DEBUG": "0", "SECRET_KEY": "x" * 50}) == "True"


def test_the_breathe_key_is_stripped():
    """A key pasted with a line ending would make http.client refuse the
    header, quoting the key in its error."""
    assert _settings_value("s.BREATHE_API_KEY",
                           {"DEBUG": "0", "SECRET_KEY": "x" * 50,
                            "BREATHE_API_KEY": "k-123\r\n"}) == "'k-123'"


def test_the_dev_key_is_private_to_the_checkout(tmp_path, monkeypatch):
    """It was the constant "dev-insecure-key", published in this repository:
    a server run with DEBUG=1 and no SECRET_KEY could have every session
    forged. Now a random key per checkout, kept across restarts."""
    from config import settings as s
    assert "dev-insecure-key" not in (ROOT / "config" / "settings.py").read_text()
    monkeypatch.setattr(s, "BASE_DIR", tmp_path)
    first = s._dev_secret_key()
    assert len(first) >= 50
    key_file = tmp_path / ".dev_secret_key"
    assert key_file.stat().st_mode & 0o077 == 0
    assert s._dev_secret_key() == first
    assert ".dev_secret_key" in (ROOT / ".gitignore").read_text()


# --- the request log ------------------------------------------------------------------

@pytest.fixture
def access(caplog):
    caplog.set_level(logging.INFO, logger="rota.access")
    return lambda: [r.getMessage() for r in caplog.records if r.name == "rota.access"]


@pytest.mark.django_db
def test_each_request_is_logged_with_the_real_client_address(access, gp_client, gp_user):
    gp_client.get("/me/?week=2026-09-28", REMOTE_ADDR=TUNNEL,
                  HTTP_CF_CONNECTING_IP="198.51.100.20")
    (line,) = [m for m in access() if " /me/ " in m]
    assert line.startswith(f"198.51.100.20 user={gp_user.pk} GET /me/ 200 ")
    assert "week=" not in line, "query strings are not logged"


@pytest.mark.django_db
def test_a_password_links_token_never_reaches_the_log(access):
    Client().get("/accounts/reset/MQ/cyb2kd-0123456789abcdef0123456789abcdef/")
    lines = access()
    assert any("/accounts/reset/<redacted>/" in m for m in lines)
    assert not any("0123456789abcdef" in m or "MQ" in m for m in lines)


@pytest.mark.django_db
def test_a_csrf_failure_reaches_the_security_log(caplog):
    caplog.set_level(logging.INFO, logger="django.security")
    Client(enforce_csrf_checks=True).post("/accounts/login/", {"username": "x", "password": "y"})
    assert any(r.name == "django.security.csrf" for r in caplog.records)


# --- the Breathe key in errors ------------------------------------------------------------

def test_a_header_error_never_repeats_the_key():
    from rota.services.breathe.client import BreatheClient, BreatheError

    def opener(req):
        # what http.client raises for a header value with a line break in it
        raise ValueError(f"Invalid header value {req.get_header('X-api-key')!r}")

    with pytest.raises(BreatheError) as exc:
        BreatheClient("SUPERSECRETKEY\n", "https://api.breathehr.com/v1",
                      opener=opener).fetch_all("employees")
    assert "SUPERSECRETKEY" not in str(exc.value)
    assert "line break" in str(exc.value)


@pytest.mark.django_db
def test_a_failed_sync_strikes_the_key_from_the_stored_error(settings):
    from rota.services.breathe import sync

    settings.BREATHE_API_KEY = "SUPERSECRETKEY"

    class Leaky:
        def fetch_all(self, resource):
            raise RuntimeError("something quoted SUPERSECRETKEY back")

    result = sync.run(Leaky())
    assert not result.ok
    assert "SUPERSECRETKEY" not in result.error and "[BREATHE_API_KEY]" in result.error
