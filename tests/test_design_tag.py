import pytest
from django.template import Context, Template

from rota import palette

pytestmark = pytest.mark.django_db


def _render():
    return Template("{% load design %}{% palette_css %}").render(Context({}))


def test_emits_a_style_block():
    out = _render()
    assert out.strip().startswith("<style>")
    assert out.strip().endswith("</style>")


def test_defines_every_tint_in_both_themes():
    out = _render()
    for key, tint in palette.TINTS.items():
        assert f"--tint-{key}-bg: {tint.bg}" in out
        assert f"--tint-{key}-fg: {tint.fg}" in out
        assert tint.dark_bg in out
        assert tint.dark_fg in out


def test_dark_overrides_are_guarded_for_both_states():
    out = _render()
    assert "@media (prefers-color-scheme: dark)" in out
    assert ':root:not([data-theme="light"])' in out
    assert ':root[data-theme="dark"]' in out


def test_grid_page_includes_the_palette(admin_client):
    from rota.models import PracticeSettings
    from tests.factories import MON, make_clinician
    PracticeSettings.load()
    make_clinician()
    html = admin_client.get(f"/rota/?week={MON}").content.decode()
    assert "--tint-" in html
