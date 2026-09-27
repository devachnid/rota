"""The Content-Security-Policy (config/middleware.py): on every page the app
renders, no script but the app's own files, and nothing in the app's own
pages that the policy would have to be loosened for."""

import re
from pathlib import Path

import pytest
from django.test import Client

from tests.factories import MON, make_clinician, make_entry, make_session_type

pytestmark = pytest.mark.django_db
ROOT = Path(__file__).resolve().parents[1]
INLINE_HANDLER = re.compile(r"""\son[a-z]+\s*=""", re.I)
INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.I)


def _policy(resp):
    return {d.split()[0]: d.split()[1:] for d in resp["Content-Security-Policy"].split("; ")}


# --- the header -----------------------------------------------------------------

def test_app_pages_carry_the_policy(gp_client):
    policy = _policy(gp_client.get("/me/"))
    scripts = policy["script-src"]
    assert scripts[0] == "'self'" and scripts[1].startswith("'nonce-")
    assert len(scripts) == 2, "nothing but the app's own scripts and Cloudflare's nonce"
    for directive in ("object-src", "base-uri"):
        assert policy[directive] == ["'none'"]
    assert policy["frame-ancestors"] == ["'none'"]
    assert policy["form-action"] == ["'self'"]


def test_signed_out_pages_carry_it_too():
    assert "Content-Security-Policy" in Client().get("/accounts/login/")


def test_the_nonce_is_new_every_time(gp_client):
    first = _policy(gp_client.get("/me/"))["script-src"][1]
    second = _policy(gp_client.get("/me/"))["script-src"][1]
    assert first != second


def test_the_admin_and_non_html_are_left_alone(admin_client, gp_client):
    """unfold's admin runs Alpine, which needs eval; JSON and static files
    are not documents."""
    assert "Content-Security-Policy" not in admin_client.get("/admin/")
    assert "Content-Security-Policy" not in gp_client.get("/manifest.webmanifest")


def test_report_only_is_the_way_back(gp_client, settings):
    settings.CSP_REPORT_ONLY = True
    resp = gp_client.get("/me/")
    assert "Content-Security-Policy" not in resp
    assert "script-src 'self' 'nonce-" in resp["Content-Security-Policy-Report-Only"]


# --- nothing in the app needs the policy loosened -------------------------------------

def _templates():
    for base in (ROOT / "templates", ROOT / "rota" / "templates"):
        for path in base.rglob("*.html"):
            if "admin" in path.relative_to(base).parts:
                continue
            yield path


def test_no_template_has_inline_script_or_handlers():
    bad = []
    for path in _templates():
        text = path.read_text()
        for pattern, what in ((INLINE_HANDLER, "inline handler"), (INLINE_SCRIPT, "inline <script>")):
            for m in pattern.finditer(text):
                bad.append(f"{path.relative_to(ROOT)}: {what}: {text[m.start():m.start() + 60]!r}")
        if re.search(r"""hx-(vals|headers)=['"]js:|hx-on""", text):
            bad.append(f"{path.relative_to(ROOT)}: htmx code that needs eval")
    assert not bad, bad


def test_htmx_is_told_never_to_evaluate(gp_client):
    html = gp_client.get("/me/").content.decode()
    assert '<meta name="htmx-config" content=\'{"allowEval": false, "allowScriptTags": false}\'>' in html


def test_rendered_pages_and_fragments_hold_no_inline_script(admin_client, gp_client):
    """The rendered output, so includes and partials count too: the pages,
    and the four forms htmx swaps into the modal."""
    c = make_clinician("Ann Invented")
    make_entry(c, day=MON, part="AM", session_type=make_session_type("Routine", code="ROUT"))
    urls = [(gp_client, u) for u in ("/me/", "/rota/", "/rota/day/", "/rota/week/",
                                     "/accounts/account/", "/reports/fairness/",
                                     "/feedback/form/")]
    urls += [(admin_client, u) for u in (
        f"/rota/?week={MON}", f"/rota/cell/{c.pk}/{MON}/AM/", f"/rota/daynote/{MON}/",
        f"/rota/locum/new/?day={MON}&part=AM", "/rota/fill/", "/requests/")]
    urls += [(Client(), u) for u in ("/accounts/login/", "/accounts/password_reset/",
                                     "/offline/")]
    bad = []
    for client, url in urls:
        resp = client.get(url, HTTP_HX_REQUEST="true") if "/cell/" in url or "/daynote/" in url \
            or "/locum/" in url or "/feedback/" in url else client.get(url)
        assert resp.status_code == 200, (url, resp.status_code)
        html = resp.content.decode()
        for pattern, what in ((INLINE_HANDLER, "handler"), (INLINE_SCRIPT, "script")):
            bad += [f"{url}: {what}: {html[m.start():m.start() + 60]!r}"
                    for m in pattern.finditer(html)]
    assert not bad, bad
