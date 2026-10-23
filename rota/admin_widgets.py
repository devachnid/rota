"""A swatch picker for the 42 session tints.

A `<select>` of 42 names tells you nothing about the colours, and styling
`<option>` backgrounds is not reliable across browsers — so this renders the
palette as labelled radio swatches instead, which is also a better way to pick
from 42 than a long dropdown.

Every colour comes from `rota.palette`; nothing here hardcodes one.
"""

from django import forms
from django.conf import settings
from django.core.cache import cache
from django.forms.widgets import RadioSelect
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from rota import palette
from rota.services.findmyshift.client import FindMyShiftError, from_settings


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


_STAFF_KEY = "findmyshift:staff"
_STAFF_TTL = 300


def findmyshift_staff():
    """The projected staff list, or None when FindMyShift is off or down.
    Cached so opening ten clinician forms costs one request."""
    cached = cache.get(_STAFF_KEY)
    if cached is not None:
        return cached
    client = from_settings()
    if client is None:
        return None
    try:
        staff = client.staff(settings.FINDMYSHIFT_TEAM_ID or None)
    except FindMyShiftError:
        return None
    staff = [s for s in staff if s.get("id") is not None]
    cache.set(_STAFF_KEY, staff, _STAFF_TTL)
    return staff


def staff_label(s):
    name = f"{s.get('firstName') or ''} {s.get('lastName') or ''}".strip()
    bits = [name, s.get("emailAddress") or "", s.get("payrollId") or ""]
    label = " · ".join(b for b in bits if b) or f"#{s.get('id')}"
    if s.get("dateFinished"):
        label += " (left)"
    return label


class StaffSelect(forms.Select):
    """A dropdown of FindMyShift staff; built per form so the cache decides
    how often FindMyShift is actually asked."""

    def __init__(self, staff, attrs=None):
        choices = [("", "— not linked —")] + [
            (str(s["id"]), staff_label(s))
            for s in sorted(staff, key=lambda s: (s.get("lastName") or "", s.get("firstName") or ""))
        ]
        super().__init__(attrs, choices)
