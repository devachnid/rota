"""Two ways a session type can be configured so the week grid cannot show
it, and nothing says so.

**A code the cell cannot print.** The grid gives each session a 3.5rem
column (`.table-grid`'s min-width in static/css/components.css, pinned by
tests/test_css_cascade.py), which leaves about 48px inside the chip once
the border-spacing and the chip's own padding are taken off. Measured
against static/fonts/plus-jakarta-sans-latin.woff2 at the chip's 11.5px,
six characters fit and eight do not — "PMC Rout" wants 54px, "Research"
51px — so they are clipped with an ellipsis. The field allows eight
because shortening it would invalidate codes already in use; this reports
the ones that will not read.

**A colour another type already has.** The palette (rota/palette.py) holds
20 hues at two tones precisely so a *related* pair can share a hue at two
weights — Urgent against Routine, SDL against VTS. Two types on the exact
same tint is different: their chips are indistinguishable, and the only
way to tell them apart on the grid is the code that may itself be clipped.

The neutral family is the one exception, and not a special case: the
palette deliberately keeps the neutral out of HUES because a neutral is
the absence of a hue rather than another position on the ring. Leave is
grey on purpose — it must not compete with the clinical sessions around
it — so the absence types seeded by migration 0022 share the neutral pair
by design, and sharing it is not a misconfiguration.

Neither is visible from a session type's own admin page, which is why the
dashboard asks here.
"""

from collections import defaultdict
from dataclasses import dataclass

from rota import palette
from rota.models import SessionType

# Characters that fit a grid chip. See the module docstring for where the
# number comes from; revisit it if the 3.5rem column ever changes.
CODE_FITS = 6


@dataclass(frozen=True)
class GridLegibility:
    """`clipped`: names of types whose code is too long, alphabetically.
    `sharing`: (tint, names) for every tint more than one type holds."""

    clipped: list[str]
    sharing: list[tuple[str, list[str]]]

    @property
    def sharing_count(self):
        """Types to fix, not collisions to fix: three types on one colour is
        three names on the list the dashboard links to."""
        return sum(len(names) for _, names in self.sharing)


def grid_legibility():
    """One pass over the session types; both answers."""
    rows = list(SessionType.objects.values_list("name", "code", "colour"))
    neutral = {f"{palette.NEUTRAL}-{tone}" for tone in palette.TONES}
    by_tint = defaultdict(list)
    for name, _, colour in rows:
        if colour not in neutral:
            by_tint[colour].append(name)
    return GridLegibility(
        clipped=sorted(name for name, code, _ in rows if len(code) > CODE_FITS),
        sharing=sorted((tint, sorted(names))
                       for tint, names in by_tint.items() if len(names) > 1),
    )
