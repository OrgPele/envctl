from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from envctl_engine.config.source_discovery import parse_envctl_text


MANAGED_AGENTS_START = "<!-- ENVCTL_AGENTS_START -->"
MANAGED_AGENTS_END = "<!-- ENVCTL_AGENTS_END -->"
AGENTS_TEMPLATE_NAME = "AGENTS.md.tpl"
_CODEGRAPH_DISABLED_VALUES = frozenset(("disabled", "disable", "off", "false", "0", "no"))
_CODEGRAPH_ENABLED_VALUES = frozenset(("enabled", "enable", "on", "true", "1", "yes"))


@dataclass(frozen=True, slots=True)
class AgentInstructionSection:
    heading: str
    body: str

    def render(self) -> str:
        return f"## {self.heading}\n\n{self.body.strip()}\n"


@dataclass(frozen=True, slots=True)
class AgentInstructionsStatus:
    path: Path
    updated: bool
    warning: str | None = None


def ensure_repo_agent_instructions(base_dir: Path) -> AgentInstructionsStatus:
    path = Path(base_dir).resolve() / "AGENTS.md"
    try:
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        updated = merge_repo_agent_instructions(existing, base_dir=path.parent)
        if updated == existing:
            return AgentInstructionsStatus(path=path, updated=False)
        _atomic_write_text(path, updated)
        return AgentInstructionsStatus(path=path, updated=True)
    except OSError as exc:
        return AgentInstructionsStatus(path=path, updated=False, warning=str(exc))


def merge_repo_agent_instructions(existing: str, *, base_dir: Path) -> str:
    base_text = _remove_managed_block(existing)
    sections = [
        section
        for section in _desired_agent_sections(base_dir)
        if f"## {section.heading}" not in base_text
    ]
    if not sections:
        return base_text

    block = _render_managed_block(sections)
    if base_text.strip():
        return base_text.rstrip() + "\n\n" + block
    return block


def _desired_agent_sections(base_dir: Path) -> list[AgentInstructionSection]:
    sections: list[AgentInstructionSection] = []
    if _serena_configured(base_dir):
        sections.append(_serena_section())
    if _codegraph_configured(base_dir):
        sections.append(_codegraph_section())
    sections.append(_development_discipline_section())
    sections.append(_envctl_workflow_section())
    return sections


def _serena_configured(base_dir: Path) -> bool:
    return (base_dir / ".serena" / "project.yml").is_file()


def _codegraph_configured(base_dir: Path) -> bool:
    raw = _repo_envctl_value(base_dir, "ENVCTL_WORKTREE_CODEGRAPH_INDEX").strip().lower()
    if raw in _CODEGRAPH_DISABLED_VALUES:
        return False
    if raw in _CODEGRAPH_ENABLED_VALUES:
        return True
    return (base_dir / ".codegraph").is_dir()


def _repo_envctl_value(base_dir: Path, key: str) -> str:
    for filename in (".envctl", ".envctl.sh"):
        path = base_dir / filename
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        parsed = parse_envctl_text(text)
        if key in parsed:
            return str(parsed.get(key, "") or "")
    return ""


def _serena_section() -> AgentInstructionSection:
    return AgentInstructionSection(
        heading="Serena",
        body=(
            "This project is configured for Serena symbolic code navigation via "
            "`.serena/project.yml`.\n\n"
            "- Activate the current checkout/worktree before structural code navigation.\n"
            "- Use Serena for symbol definitions, references, diagnostics, and semantic edits.\n"
            "- Use `rg` for exact strings such as flags, env keys, log messages, "
            "config values, and docs prose.\n"
            "- After structural code changes, let Serena refresh automatically; if "
            "results look stale, run `serena project health-check` from the repo root."
        ),
    )


def _codegraph_section() -> AgentInstructionSection:
    return AgentInstructionSection(
        heading="CodeGraph",
        body=(
            "This project is configured for CodeGraph repo context.\n\n"
            "- Use CodeGraph for broad structure, call-path, flow, or blast-radius questions "
            "when the current checkout has an active index.\n"
            "- Use direct file reads or configured symbol tooling for line-level edits and diagnostics.\n"
            "- Skip CodeGraph entirely when this checkout has no active CodeGraph metadata or index."
        ),
    )


def _development_discipline_section() -> AgentInstructionSection:
    return AgentInstructionSection(
        heading="Development Discipline",
        body=(
            "- For code changes, start with `git status --short` and inspect the relevant "
            "diff before editing. Preserve unrelated user changes.\n"
            "- Read the owning code path before changing it. Prefer existing local helpers, "
            "patterns, and tests over new abstractions.\n"
            "- Keep changes scoped to the task; avoid unrelated refactors, formatting churn, "
            "or generated metadata changes.\n"
            "- For behavior changes, add or update the smallest test that proves the real "
            "contract, then report the validation actually run.\n"
            "- If a required check cannot run, say why and name the remaining risk."
        ),
    )


def _envctl_workflow_section() -> AgentInstructionSection:
    return AgentInstructionSection(
        heading="Envctl Workflow",
        body=(
            "- Keep edits inside the current checkout/worktree and preserve unrelated user changes.\n"
            "- During implementation, run `envctl test-focused` from inside the current "
            "worktree for the normal validation loop. Use broader validation only when "
            "the focused plan recommends it or the change is cross-cutting/risky.\n"
            "- For handoff, use `envctl test-focused --ship-on-pass \"<message>\"` from "
            "inside the current worktree when a handoff message is ready; fall back to "
            "`envctl ship -m \"<message>\"` only when needed. Both use the ship workflow: "
            "it stages intended non-protected changes via git add, commits, pushes, "
            "creates/updates the PR, and reports status checks. Use raw `git` or `gh` "
            "handoff commands only when `ship` is unavailable or returns actionable "
            "fallback instructions.\n"
            "- If shipping is delegated to a real background worker, it should report only "
            "blockers; successful ship results stay silent.\n"
            "- Keep envctl-generated local artifacts uncommitted."
        ),
    )


def _render_managed_block(sections: list[AgentInstructionSection]) -> str:
    rendered_sections = _render_agents_template(sections).rstrip()
    return f"{MANAGED_AGENTS_START}\n{rendered_sections}\n{MANAGED_AGENTS_END}\n"


def _render_agents_template(sections: list[AgentInstructionSection]) -> str:
    rendered_by_heading = {section.heading: section.render().strip() for section in sections}
    replacements = {
        "SERENA_SECTION": rendered_by_heading.get("Serena", ""),
        "CODEGRAPH_SECTION": rendered_by_heading.get("CodeGraph", ""),
        "DEVELOPMENT_DISCIPLINE_SECTION": rendered_by_heading.get(
            "Development Discipline",
            "",
        ),
        "ENVCTL_WORKFLOW_SECTION": rendered_by_heading.get("Envctl Workflow", ""),
    }
    rendered_sections: list[str] = []
    for line in _agents_template_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith("{{") or not stripped.endswith("}}"):
            continue
        key = stripped[2:-2].strip()
        if value := replacements.get(key):
            rendered_sections.append(value)
    return "\n\n".join(rendered_sections)


def _agents_template_text() -> str:
    return (files(__package__) / AGENTS_TEMPLATE_NAME).read_text(encoding="utf-8")


def _remove_managed_block(text: str) -> str:
    start = text.find(MANAGED_AGENTS_START)
    if start == -1:
        return text
    end = text.find(MANAGED_AGENTS_END, start)
    if end == -1:
        return text
    end += len(MANAGED_AGENTS_END)
    before = text[:start].rstrip()
    after = text[end:].lstrip("\n")
    if before and after:
        return before + "\n\n" + after
    if before:
        return before + "\n"
    return after


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)
