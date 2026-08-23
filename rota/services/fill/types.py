from dataclasses import dataclass, field
from datetime import date


def site_for(session_type, override=None):
    """Site precedence for a placement: an explicit override (e.g. a
    RecurringCommitment's own site) wins, else the session type's
    default_site. Shared by every placement call site so a new one can't
    forget to thread it."""
    return override or session_type.default_site


@dataclass
class UnfilledSlot:
    day: date
    part: str | None
    session_type: str
    reason: str


@dataclass
class FillResult:
    created: int = 0
    unfilled: list[UnfilledSlot] = field(default_factory=list)
