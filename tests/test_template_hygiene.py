"""Template mistakes that render to the page instead of failing.

Django's `{# ... #}` is a SINGLE-LINE comment. Spread one over several lines
and it is not recognised as a comment at all — the whole thing is emitted to
the page as literal text. One did exactly that, appearing under the "Leave"
heading of the requests inbox in production, because no test renders a page
and asserts that developer notes are absent from it.

`{% comment %} ... {% endcomment %}` is the multi-line form.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
TEMPLATE_FILES = sorted(TEMPLATES.rglob("*.html"))


@pytest.mark.parametrize("path", TEMPLATE_FILES, ids=lambda p: p.name)
def test_no_multiline_hash_comments(path):
    """A `{#` with no `#}` on the same line is a multi-line comment attempt."""
    offenders = []
    for lineno, line in enumerate(path.read_text().split("\n"), 1):
        for m in re.finditer(r"\{#", line):
            if "#}" not in line[m.end():]:
                offenders.append(f"{path.name}:{lineno}: {line.strip()[:70]}")
    assert not offenders, (
        "Django's {# #} is single-line only — these span lines and will render "
        "to the page as literal text. Use {% comment %}...{% endcomment %}:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("path", TEMPLATE_FILES, ids=lambda p: p.name)
def test_comment_and_block_tags_are_balanced(path):
    body = path.read_text()
    opens = len(re.findall(r"\{%\s*comment\s*%\}", body))
    closes = len(re.findall(r"\{%\s*endcomment\s*%\}", body))
    assert opens == closes, (
        f"{path.name}: {opens} {{% comment %}} vs {closes} {{% endcomment %}} — "
        f"an unbalanced pair swallows or leaks page content"
    )


# --------------------------------------------------------------------------
# and the actual rendered pages, which is what the reader sees
# --------------------------------------------------------------------------

# Fragments that mean a developer note escaped into the page. Deliberately
# narrow: real copy never contains these.
LEAKED = ["{#", "#}", "{% comment", "{%comment", "endcomment",
          "TODO:", "FIXME:", "XXX:", "vestigial"]


@pytest.mark.django_db
@pytest.mark.parametrize("url", ["/rota/", "/me/", "/requests/", "/rota/fill/",
                                 "/reports/fairness/", "/reports/leave/",
                                 "/reports/staffing/", "/reports/trainees/",
                                 "/me/leave/new/", "/me/swap/new/"])
def test_no_developer_notes_reach_the_rendered_page(admin_client, url):
    from rota.models import PracticeSettings
    PracticeSettings.load()
    html = admin_client.get(url).content.decode()
    for frag in LEAKED:
        assert frag not in html, (
            f"{url} renders {frag!r} to the page — a template comment or note "
            f"has leaked into what the user reads"
        )


@pytest.mark.django_db
def test_the_login_page_is_clean_too(client):
    html = client.get("/accounts/login/").content.decode()
    for frag in LEAKED:
        assert frag not in html, f"/accounts/login/ renders {frag!r}"
