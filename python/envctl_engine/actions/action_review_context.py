from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol


class ReviewActionContext(Protocol):
    @property
    def repo_root(self) -> Path: ...

    @property
    def project_root(self) -> Path: ...

    @property
    def project_name(self) -> str: ...

    @property
    def env(self) -> Mapping[str, str]: ...

    @property
    def interactive(self) -> bool: ...
