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

# A parser-level sanity bound, not a domain one. Every field that uses this
# holds months or weekdays, so any range spanning more than a thousand values
# is a typo — and materialising it is how one extra digit turns a coverage
# rule into a hundred-million-element list. The bounds check in
# validate_int_list runs too late to help: parse_int_list has already built
# the list by then.
_MAX_SPAN = 1000

# _MAX_SPAN bounds each hyphen segment on its own, and segments compose:
# fifty thousand legal `1-1000` segments cost exactly what one illegal
# `1-50000000` costs, and cost it inside a fill run. So the total needs its
# own bound. Ten thousand is ten times the per-segment cap — far above the
# twelve months or seven weekdays any real field holds, far below anything
# that costs real memory or real time.
_MAX_TOTAL = 10_000

_TOO_MANY = (
    "%(part)r takes this past %(cap)s values in total. That limit is on the "
    "whole value, not on any single range, so shortening one range may not be "
    "enough. It is almost certainly a typo, not a genuine month or weekday "
    "list."
)


def _renderable(number: int) -> str:
    """str() of an int is capped at 4300 digits, the same cap int() applies to
    the string it parses — so `0-<4300 nines>` yields a span one digit longer
    than either bound and one digit too long to render. A refusal message that
    raises ValueError while Django formats it is precisely the escape this
    module exists to prevent."""
    try:
        return str(number)
    except ValueError:
        return "an unwriteably large number of"


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
            span = high - low + 1
            if span > _MAX_SPAN:
                raise ValidationError(
                    "%(part)r spans %(span)s values, more than the %(cap)s-value "
                    "limit for a single range. That is almost certainly a typo, "
                    "not a genuine month or weekday range.",
                    params={
                        "part": part,
                        "span": _renderable(span),
                        "cap": _MAX_SPAN,
                    },
                )
            if len(out) + span > _MAX_TOTAL:
                raise ValidationError(
                    _TOO_MANY, params={"part": part, "cap": _MAX_TOTAL}
                )
            out.extend(range(low, high + 1))
        else:
            if not (part.isascii() and part.isdigit()):
                raise ValidationError(_ERROR, params={"part": part})
            if len(out) >= _MAX_TOTAL:
                # plain numbers compose the same way ranges do, one at a time
                raise ValidationError(
                    _TOO_MANY, params={"part": part, "cap": _MAX_TOTAL}
                )
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
