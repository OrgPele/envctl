from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class TestCommandSpec:
    command: list[str]
    cwd: Path
    source: str


SuggestionConfidence = Literal["high", "medium", "low"]
SuggestionTarget = Literal["backend", "frontend", "action"]


@dataclass(frozen=True)
class TestCommandSuggestion:
    command_text: str
    command: list[str]
    cwd: Path
    source: str
    label: str
    confidence: SuggestionConfidence
    reason: str
    target: SuggestionTarget
    is_default: bool = False


@dataclass(frozen=True)
class TestPathSuggestion:
    path: str
    source: str
    label: str
    confidence: SuggestionConfidence
    reason: str
    is_default: bool = False
