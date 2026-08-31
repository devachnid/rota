"""A swatch picker for the 42 session tints.

A `<select>` of 42 names tells you nothing about the colours, and styling
`<option>` backgrounds is not reliable across browsers — so this renders the
palette as labelled radio swatches instead, which is also a better way to pick
from 42 than a long dropdown.

Every colour comes from `rota.palette`; nothing here hardcodes one.
"""

from django.forms.widgets import RadioSelect
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from rota import palette


class TintSwatchSelect(RadioSelect):
    """Radio inputs painted in the tint each one selects."""

    def render(self, name, value, attrs=None, renderer=None):
        rows = format_html_join(
            "\n",
            '<label style="display:inline-block; margin:2px; padding:4px 8px; '
            'border-radius:6px; cursor:pointer; font-size:12px; '
            'background:{}; color:{}; outline:{}">'
            '<input type="radio" name="{}" value="{}"{}> {}</label>',
            (
                (
                    tint.bg,
                    tint.fg,
                    "2px solid currentColor" if key == value else "none",
                    name,
                    key,
                    mark_safe(" checked") if key == value else "",
                    tint.label,
                )
                for key, tint in palette.TINTS.items()
            ),
        )
        return format_html(
            '<div style="max-width:52em; line-height:2">{}</div>', rows)
