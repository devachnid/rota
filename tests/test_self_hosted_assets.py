"""Every asset a page loads must come from this server.

The app was loading Plus Jakarta Sans from fonts.googleapis.com, which sent
each clinician's IP address to a third party on every page load. At a UK GP
practice that is a data-protection question with no upside, so the font is
now served from `static/fonts/`.

A regression here is silent — the page looks identical whether the font came
from disk or from Google — so it gets a test rather than a code comment.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
CSS_DIR = ROOT / "static" / "css"
FONT_DIR = ROOT / "static" / "fonts"

# Hosts that would take a request off this box. Not exhaustive as a blocklist —
# the URL-scheme test below is the real guard; these just name the specific
# regression for a clearer failure message.
THIRD_PARTY = ("fonts.googleapis.com", "fonts.gstatic.com", "cdn.jsdelivr.net",
               "cdnjs.cloudflare.com", "unpkg.com")


def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _strip_django_comments(html: str) -> str:
    html = re.sub(r"\{#.*?#\}", "", html, flags=re.S)
    return re.sub(r"<!--.*?-->", "", html, flags=re.S)


TEMPLATE_FILES = sorted(TEMPLATES.rglob("*.html"))
CSS_FILES = sorted(CSS_DIR.glob("*.css"))


@pytest.mark.parametrize("path", TEMPLATE_FILES, ids=lambda p: p.name)
def test_templates_load_nothing_from_a_third_party(path):
    body = _strip_django_comments(path.read_text())
    for host in THIRD_PARTY:
        assert host not in body, (
            f"{path.relative_to(ROOT)} references {host}; every asset must be "
            f"served from this box so no clinician's IP leaves it"
        )
    external = re.findall(r'(?:href|src)\s*=\s*["\'](https?://[^"\']+)', body)
    assert not external, (
        f"{path.relative_to(ROOT)} loads {external} over http(s); use "
        f"{{% static %}} so the asset is served locally"
    )


@pytest.mark.parametrize("path", CSS_FILES, ids=lambda p: p.name)
def test_stylesheets_fetch_nothing_from_a_third_party(path):
    body = _strip_css_comments(path.read_text())
    for host in THIRD_PARTY:
        assert host not in body, f"{path.name} references {host}"
    remote = re.findall(r"url\(\s*['\"]?(https?://[^)'\"]+)", body)
    assert not remote, f"{path.name} fetches {remote} remotely"
    assert "@import" not in body, (
        f"{path.name} uses @import, which can pull in a remote stylesheet and "
        f"is invisible to the url() check above"
    )


def test_the_font_files_are_actually_present_and_are_woff2():
    files = sorted(FONT_DIR.glob("*.woff2"))
    assert files, "no woff2 files in static/fonts/ — the @font-face src is dangling"
    for f in files:
        assert f.read_bytes()[:4] == b"wOF2", f"{f.name} is not a woff2 file"


def test_every_font_face_src_resolves_to_a_file_on_disk():
    css = _strip_css_comments((CSS_DIR / "fonts.css").read_text())
    srcs = re.findall(r"url\(\s*['\"]?([^)'\"]+\.woff2)", css)
    assert srcs, "fonts.css declares no woff2 source"
    for src in srcs:
        resolved = (CSS_DIR / src).resolve()
        assert resolved.is_file(), (
            f"fonts.css points at {src}, which resolves to {resolved} and does "
            f"not exist — the browser would silently fall back to a system font"
        )


def test_the_licence_ships_with_the_font():
    ofl = FONT_DIR / "OFL.txt"
    assert ofl.is_file(), "the SIL Open Font Licence must ship alongside the font"
    assert "SIL OPEN FONT LICENSE" in ofl.read_text().upper()


@pytest.mark.django_db
def test_a_rendered_page_references_the_local_font_and_no_remote_one(client):
    html = client.get("/accounts/login/").content.decode()
    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html
    assert "css/fonts.css" in html, "the page does not link the local font stylesheet"
