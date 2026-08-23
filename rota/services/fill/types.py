from dataclasses import dataclass, field
from datetime import date


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
