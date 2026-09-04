"""A swatch picker for the 42 session tints.

A `<select>` of 42 names tells you nothing about the colours, and styling
`<option>` backgrounds is not reliable across browsers — so this renders the
palette as labelled radio swatches instead, which is also a better way to pick
from 42 than a long dropdown.

Every colour comes from `rota.palette`; nothing here hardcodes one.
"""

from django import forms
from django.core.cache import cache
from django.forms.widgets import RadioSelect
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from rota import palette
from rota.services.breathe.client import BreatheError, from_settings


class TintSwatchSelect(RadioSelect):
    """Radio inputs painted in the tint each one selects, and the chosen one
    shown large. Colours are inline because there are 42 of them and they
    come from rota.palette, not from a stylesheet."""

    def render(self, name, value, attrs=None, renderer=None):
        chosen = palette.TINTS.get(value)
        preview = ""
        if chosen:
            preview = format_html(
                '<div class="mb-3 inline-block rounded-default px-4 py-2 font-semibold" '
                'style="background:{}; color:{}">{}</div>',
                chosen.bg, chosen.fg, chosen.label)
        rows = format_html_join(
            "\n",
            '<label class="inline-block cursor-pointer rounded-default px-2 py-1 text-xs '
            'font-semibold" style="background:{}; color:{}; outline:{}">'
            '<input type="radio" name="{}" value="{}"{}> {}</label>',
            (
                (tint.bg, tint.fg,
                 "2px solid currentColor" if key == value else "none",
                 name, key,
                 mark_safe(" checked") if key == value else "",
                 tint.label)
                for key, tint in palette.TINTS.items()
            ),
        )
        return format_html(
            '<div>{}<div class="flex flex-wrap gap-1" style="max-width:52em">{}</div></div>',
            preview, rows)


_EMPLOYEES_KEY = "breathe:employees"
_EMPLOYEES_TTL = 300


def breathe_employees():
    """The projected employee list, or None when Breathe is off or down.
    Cached so opening ten clinician forms costs one request."""
    cached = cache.get(_EMPLOYEES_KEY)
    if cached is not None:
        return cached
    client = from_settings()
    if client is None:
        return None
    try:
        employees = client.employees()
    except BreatheError:
        return None
    cache.set(_EMPLOYEES_KEY, employees, _EMPLOYEES_TTL)
    return employees


def employee_label(e):
    name = f"{e.get('first_name') or ''} {e.get('last_name') or ''}".strip()
    bits = [name, e.get("email") or "", e.get("employee_ref") or ""]
    label = " · ".join(b for b in bits if b)
    if (e.get("status") or "").lower().startswith("ex"):
        label += " (ex-employee)"
    return label


class BreatheEmployeeSelect(forms.Select):
    """A dropdown of Breathe employees; built per form so the cache decides
    how often Breathe is actually asked."""

    def __init__(self, employees, attrs=None):
        choices = [("", "— not linked —")] + [
            (e["id"], employee_label(e))
            for e in sorted(employees, key=lambda e: (e.get("last_name") or "", e.get("first_name") or ""))
        ]
        super().__init__(attrs, choices)
