from __future__ import annotations

from dataclasses import dataclass, field


class RouteError(ValueError):
    """Raised when CLI route parsing fails."""


@dataclass(slots=True)
class Route:
    command: str
    mode: str
    raw_args: list[str] = field(default_factory=list)
    passthrough_args: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    flags: dict[str, object] = field(default_factory=dict)
