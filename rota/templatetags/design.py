from django import template
from django.utils.safestring import mark_safe

from rota import palette

register = template.Library()


def _build_css() -> str:
    light = "\n".join(
        f"  --tint-{k}-bg: {t.bg}; --tint-{k}-fg: {t.fg};"
        for k, t in palette.TINTS.items()
    )
    dark = "\n".join(
        f"    --tint-{k}-bg: {t.dark_bg}; --tint-{k}-fg: {t.dark_fg};"
        for k, t in palette.TINTS.items()
    )
    return (
        "<style>\n:root {\n" + light + "\n}\n"
        "@media (prefers-color-scheme: dark) {\n"
        '  :root:not([data-theme="light"]) {\n' + dark + "\n  }\n}\n"
        ':root[data-theme="dark"] {\n' + dark.replace("    ", "  ") + "\n}\n"
        "</style>"
    )


_CSS = _build_css()  # the palette is static; build once at import


@register.simple_tag
def palette_css():
    return mark_safe(_CSS)
