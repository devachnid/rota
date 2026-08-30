"""Comma-separated integer lists that also accept ranges.

Coverage rules take months and weekdays as free text. The original parse was
`int(x) for x in value.split(",")`, so `1-6,9-12` — the obvious way to write
"the winter half of the year" — raised ValueError from inside a fill run, in
front of whoever pressed the button rather than whoever typed the value.

Parsing and validation live together here so every field that takes this shape
behaves the same way: CoverageRule.months, .weekdays and .preferred_weekdays,
and PracticeSettings.open_weekdays.
"""

from django.core.exceptions import ValidationError

_ERROR = (
    "%(part)r is not a number or a range like 1-6. "
    "Use commas between values, for example 1,3,5 or 1-6,9-12."
)


def parse_int_list(value: str) -> list[int]:
    """1-6,9-12 -> [1,2,3,4,5,6,9,10,11,12]. Blank -> []."""
    out: list[int] = []
    for raw in (value or "").split(","):
        part = raw.strip()
        if not part:
            if (value or "").strip():
                # "1,,2" is a typo, not an empty list
                raise ValidationError(_ERROR, params={"part": raw})
            continue
        if "-" in part:
            bits = part.split("-")
            if len(bits) != 2 or not all(
                b.strip().isascii() and b.strip().isdigit() for b in bits
            ):
                raise ValidationError(_ERROR, params={"part": part})
            try:
                low, high = int(bits[0]), int(bits[1])
            except ValueError as exc:
                # isascii()+isdigit() rejects the character classes we can
                # name, but CPython also caps int()'s digit count (4300);
                # this is the belt for that belt-and-braces.
                raise ValidationError(_ERROR, params={"part": part}) from exc
            if high < low:
                raise ValidationError(
                    "%(part)r counts downwards, so it would never match anything. "
                    "Write it as %(fixed)s.",
                    params={"part": part, "fixed": f"{high}-{low}"},
                )
            out.extend(range(low, high + 1))
        else:
            if not (part.isascii() and part.isdigit()):
                raise ValidationError(_ERROR, params={"part": part})
            try:
                out.append(int(part))
            except ValueError as exc:
                raise ValidationError(_ERROR, params={"part": part}) from exc
    return out


def validate_int_list(value: str, low: int, high: int, label: str) -> None:
    """Raise if `value` does not parse, or holds anything outside [low, high]."""
    try:
        numbers = parse_int_list(value)
    except ValidationError as exc:
        raise ValidationError({label: exc.messages}) from exc
    bad = sorted({n for n in numbers if not low <= n <= high})
    if bad:
        raise ValidationError({label: [
            f"{label}: {', '.join(str(n) for n in bad)} "
            f"{'is' if len(bad) == 1 else 'are'} outside {low}-{high}."
        ]})
