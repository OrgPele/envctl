from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ProjectContextLike(Protocol):
    name: str
    root: Path


__all__ = ["ProjectContextLike"]
