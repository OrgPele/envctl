from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from envctl_engine.actions.actions_test import TestCommandSpec


@dataclass(frozen=True)
class TestTargetContext:
    project_name: str
    project_root: Path
    target_obj: object | None


@dataclass(frozen=True)
class TestExecutionSpec:
    index: int
    spec: TestCommandSpec
    args: list[str]
    resolved_source: str
    project_name: str
    project_root: Path
    target_obj: object | None = None
