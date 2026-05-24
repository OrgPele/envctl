from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class PromptInstallResult:
    cli: str
    path: str
    status: str
    backup_path: str | None
    message: str
    kind: str = "prompt"
    link_path: str | None = None


@dataclass(slots=True)
class PromptTemplate:
    name: str
    body: str


@dataclass(slots=True)
class PromptInstallPlan:
    cli: str
    preset: str
    target_path: Path
    rendered: str
    existed: bool


@dataclass(slots=True)
class CodexSkillInstallPlan:
    cli: str
    preset: str
    skill_name: str
    skill_dir: Path
    target_path: Path
    agents_path: Path
    rendered: str
    rendered_openai_yaml: str
    existed: bool


@dataclass(slots=True, frozen=True)
class CodexSkillMetadata:
    skill_name: str
    display_name: str
    short_description: str
    description: str
    default_prompt: str | None = None
