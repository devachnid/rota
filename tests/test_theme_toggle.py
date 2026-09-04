"""The theme toggle.

Frontend Phase 1 built all three CSS states — bare :root, the
prefers-color-scheme block, and [data-theme] — and deliberately left the
toggle for later. This is later.

Three states, not two: a two-way toggle would strand the prefers-color-scheme
path that currently works for everyone who has not chosen.
"""


import pytest
from django.conf import settings


def _base():
    return (settings.BASE_DIR / "templates" / "base.html").read_text()


def _script():
    return (settings.BASE_DIR / "static" / "js" / "theme.js").read_text()


def test_the_theme_is_applied_before_first_paint():
    """Applying it after the body renders means every load flashes the wrong
    theme before correcting itself."""
    import re
    base = _base()
    head = base[base.index("<head>"):base.index("</head>")]
    tags = re.findall(r"<script[^>]*theme\.js[^>]*>", head)
    assert tags, "theme.js is not loaded in <head>"
    assert not any("defer" in t or "async" in t for t in tags), (
        f"a deferred or async script runs after parsing, which is exactly the "
        f"flash this avoids: {tags}"
    )


def test_all_three_states_are_handled():
    script = _script()
    for state in ("system", "light", "dark"):
        assert f'"{state}"' in script or f"'{state}'" in script


def test_the_choice_is_persisted_and_read_back():
    script = _script()
    assert "localStorage" in script
    assert "rota-theme" in script


def test_storage_failures_do_not_break_the_page():
    """Private windows and blocked site data throw on access."""
    script = _script()
    assert "try" in script and "catch" in script


@pytest.mark.django_db
def test_the_control_is_in_the_nav(client):
    html = client.get("/accounts/login/").content.decode()
    assert 'id="theme-toggle"' in html
