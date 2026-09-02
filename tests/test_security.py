"""Security properties, pinned.

Every check here corresponds to something found in a real audit of the staging
deployment on 2026-08-26. Configuration weaknesses are silent by nature — the
app serves happily either way — so each one gets a test rather than a comment.
"""

import os
from urllib.parse import quote

import pytest
from django.conf import settings
from django.test import Client

from rota.models import PracticeSettings


# --------------------------------------------------------------------------
# 1. reflected XSS in the parse-error handler
# --------------------------------------------------------------------------

PAYLOAD = "<img src=x onerror=alert(1)>"


@pytest.mark.django_db
def test_parse_errors_do_not_reflect_markup_into_an_html_response(admin_client):
    """`/rota/daynote/<day>/` is a GET, so no CSRF token stood between an
    attacker and a logged-in admin: a crafted link was enough. Python puts the
    offending value in the exception message, and the handler used to return it
    as unescaped text/html."""
    PracticeSettings.load()
    r = admin_client.get(f"/rota/daynote/{quote(PAYLOAD)}/")

    assert r.status_code == 400
    assert not r.headers["Content-Type"].startswith("text/html"), (
        "a parse error is served as HTML, so any markup in the offending value "
        "is parsed by the browser"
    )
    body = r.content.decode()
    assert PAYLOAD not in body, "the payload came back verbatim"
    assert "&lt;img" in body, "the value should still be reported, escaped"


def test_the_error_handler_escapes_and_sends_plain_text():
    """Directly, so the guarantee does not depend on one URL keeping its
    shape."""
    from rota.views.decorators import parse_errors_as_400

    @parse_errors_as_400
    def view(request):
        int(PAYLOAD)

    r = view(None)
    assert r.status_code == 400
    assert r.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert PAYLOAD.encode() not in r.content


# --------------------------------------------------------------------------
# 2. DEBUG must fail towards safety
# --------------------------------------------------------------------------

def test_debug_defaults_to_off():
    """It defaulted to ON. A deployment that forgot the variable served
    tracebacks, published its URL map on every 404, dropped HSTS and the Secure
    cookie flags, and — because the SECRET_KEY guard only fires when DEBUG is
    off — fell back to the placeholder key committed to this repository.
    Staging did exactly that.

    Read the source rather than `settings.DEBUG`: the test runner forces DEBUG
    off, so the live value proves nothing about the default.
    """
    src = (settings.BASE_DIR / "config" / "settings.py").read_text()
    assert 'os.environ.get("DEBUG", "0")' in src, (
        "DEBUG no longer defaults to off — forgetting the variable in a "
        "deployment would silently enable it"
    )
    assert 'os.environ.get("DEBUG", "1")' not in src


def test_secret_key_is_demanded_when_debug_is_off():
    src = (settings.BASE_DIR / "config" / "settings.py").read_text()
    assert "ImproperlyConfigured" in src
    assert "SECRET_KEY env var must be set" in src


def test_the_placeholder_key_is_only_reachable_with_debug_explicitly_on():
    """The fallback key is public — it is in this file's own repository — so
    it must never be reachable by omission."""
    src = (settings.BASE_DIR / "config" / "settings.py").read_text()
    i = src.index('"dev-insecure-key"')
    assert "_TESTING" in src[i - 200:i], (
        "the placeholder SECRET_KEY is no longer guarded"
    )


# --------------------------------------------------------------------------
# 3. cookies and transport, in the configuration a deployment actually gets
# --------------------------------------------------------------------------

def test_production_settings_secure_the_cookies_and_transport():
    """Asserted against the source of the `not DEBUG` block, because the test
    process runs with DEBUG off but without the env var that triggers it."""
    src = (settings.BASE_DIR / "config" / "settings.py").read_text()
    block = src[src.index("if not DEBUG:"):]
    for setting in ("SESSION_COOKIE_SECURE = True",
                    "CSRF_COOKIE_SECURE = True",
                    "SECURE_HSTS_SECONDS",
                    "SECURE_HSTS_INCLUDE_SUBDOMAINS = True",
                    "SECURE_PROXY_SSL_HEADER"):
        assert setting in block, f"{setting} is no longer set for production"


def test_csrf_cookie_is_closed_to_scripts():
    """Nothing reads it from JS — base.html hands htmx the token from the
    template context — so an XSS should not be able to read it either."""
    assert settings.CSRF_COOKIE_HTTPONLY is True
    base = (settings.BASE_DIR / "templates" / "base.html").read_text()
    assert "csrf_token" in base and "document.cookie" not in base


def test_session_cookie_is_closed_to_scripts_and_same_site():
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE in ("Lax", "Strict")


# --------------------------------------------------------------------------
# 4. passwords
# --------------------------------------------------------------------------

@pytest.mark.parametrize("weak", ["password", "12345678", "qwertyui", "letmein1"])
@pytest.mark.django_db
def test_common_passwords_are_rejected(weak):
    from django.core.exceptions import ValidationError
    from django.contrib.auth.password_validation import validate_password

    with pytest.raises(ValidationError):
        validate_password(weak)


@pytest.mark.django_db
def test_a_password_that_looks_like_the_users_own_email_is_rejected():
    from django.core.exceptions import ValidationError
    from django.contrib.auth import get_user_model
    from django.contrib.auth.password_validation import validate_password

    user = get_user_model()(email="hannah.whitfield@example.org")
    with pytest.raises(ValidationError):
        validate_password("hannah.whitfield", user)


# --------------------------------------------------------------------------
# 5. authorisation — nothing behind the login is reachable without it
# --------------------------------------------------------------------------

PROTECTED = ["/rota/", "/me/", "/requests/", "/rota/fill/",
             "/reports/fairness/", "/reports/staffing/",
             "/reports/trainees/", "/me/swap/new/"]


@pytest.mark.django_db
@pytest.mark.parametrize("url", PROTECTED)
def test_anonymous_users_are_sent_to_login(url):
    r = Client().get(url)
    assert r.status_code in (302, 403), f"{url} served content to an anonymous user"
    if r.status_code == 302:
        assert "/accounts/login/" in r["Location"]


# Screens that change the rota or act on other people's requests.
ADMIN_ONLY = ["/requests/", "/rota/fill/", "/rota/publish/", "/rota/assign/",
              "/rota/clear/", "/rota/daynote/save/", "/rota/locum/new/",
              "/rota/locum/save/"]


@pytest.mark.django_db
@pytest.mark.parametrize("url", ADMIN_ONLY)
def test_a_plain_gp_cannot_reach_admin_screens(url, gp_client):
    r = gp_client.get(url)
    assert r.status_code in (403, 405), (
        f"{url} is reachable by a non-admin clinician (got {r.status_code})"
    )


# The four reports are login-gated, NOT admin-gated: every clinician can see
# the whole practice's figures. That is deliberate — the fairness report only
# works as a transparency mechanism if the people it is about can read it —
# but it means leave balances and trainee progress are visible to colleagues
# too. Pinned so that if it is ever narrowed, the change is a decision rather
# than a side effect.
REPORTS = ["/reports/fairness/", "/reports/staffing/",
           "/reports/trainees/"]


@pytest.mark.django_db
@pytest.mark.parametrize("url", REPORTS)
def test_reports_are_practice_wide_and_visible_to_any_clinician(url, gp_client):
    assert gp_client.get(url).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("url", REPORTS)
def test_reports_hide_unpublished_drafts_from_non_admins(url, gp_client, admin_client):
    """The one protection the reports do apply: a GP sees published reality,
    not the admin's work in progress."""
    import re
    src = (settings.BASE_DIR / "rota" / "views" / "reports.py").read_text()
    assert re.search(r"include_drafts\s*=\s*request[.]user[.]is_rota_admin", src), (
        "reports no longer gate draft visibility on admin status"
    )
    assert gp_client.get(url).status_code == 200


@pytest.mark.django_db
def test_every_rota_view_declares_an_authorisation_decorator():
    """A view added without a gate is the failure this catches — it would work
    perfectly and be open to the internet."""
    import re
    from pathlib import Path

    ungated = []
    for path in sorted((settings.BASE_DIR / "rota" / "views").glob("*.py")):
        if path.name in ("__init__.py", "decorators.py"):
            continue
        src = path.read_text()
        for m in re.finditer(r"^((?:@\w+(?:\([^)]*\))?\s*\n)*)def (\w+)\(request",
                             src, re.M):
            decorators, name = m.group(1), m.group(2)
            if name.startswith("_"):
                continue
            if not ("login_required" in decorators or "admin_required" in decorators):
                ungated.append(f"{path.name}::{name}")
    assert not ungated, (
        "these views have neither @login_required nor @admin_required: "
        + ", ".join(ungated)
    )
