from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


MANAGED_AGENTS_START = "<!-- ENVCTL_AGENTS_START -->"
MANAGED_AGENTS_END = "<!-- ENVCTL_AGENTS_END -->"


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
    if _cgc_configured(base_dir):
        sections.append(_cgc_section())
    sections.append(_envctl_workflow_section())
    return sections


def _serena_configured(base_dir: Path) -> bool:
    return (base_dir / ".serena" / "project.yml").is_file()


def _cgc_configured(base_dir: Path) -> bool:
    return (base_dir / ".cgcignore").is_file() or (base_dir / ".codegraphcontext").exists()


def _serena_section() -> AgentInstructionSection:
    return AgentInstructionSection(
        heading="Serena",
        body=(
            "This project is configured for Serena symbolic code navigation via "
            "`.serena/project.yml`.\n\n"
            "- Use Serena for symbol definitions, references, call paths, diagnostics, "
            "and semantic edits.\n"
            "- Use `rg` for exact strings such as flags, env keys, log messages, "
            "config values, and docs prose.\n"
            "- After structural code changes, let Serena refresh automatically; if "
            "results look stale, run `serena project health-check` from the repo root."
        ),
    )


def _cgc_section() -> AgentInstructionSection:
    return AgentInstructionSection(
        heading="CodeGraphContext",
        body=(
            "This project uses CodeGraphContext (`cgc`) for repo-wide graph analysis. "
            "Do not use the old `codegraph` CLI or `.codegraph/` indexes.\n\n"
            "- Use CGC for ownership, coupling, impact, hotspot, dead-code, and "
            "cross-module dependency questions.\n"
            "- Use Serena for exact symbol navigation and edits after CGC identifies "
            "the relevant files.\n"
            "- Use read-only `cgc query ...`, `cgc stats`, or `cgc report` when broad "
            "graph context is useful."
        ),
    )


def _envctl_workflow_section() -> AgentInstructionSection:
    return AgentInstructionSection(
        heading="Envctl Workflow",
        body=(
            "- During implementation, run `envctl test-focused` from inside the current "
            "worktree for the normal validation loop. Use broader validation only when "
            "the focused plan recommends it or the change is cross-cutting/risky.\n"
            "- For handoff, use `envctl ship -m \"<message>\"` from inside the current "
            "worktree. `ship` stages intended files, commits, pushes, creates or updates "
            "the PR, predicts merge conflicts, and waits for target GitHub Tests checks. "
            "Do not run separate raw `git`/`gh` commit, push, PR, or status-check commands "
            "unless `ship` is unavailable or fails with actionable fallback instructions.\n"
            "- If a real subagent or background-task tool is available, delegate "
            "`envctl ship -m \"<message>\"` there. The shipping worker should report only "
            "failures, merge conflicts, check failures/timeouts, no-checks-reported status, "
            "or actionable review comments; a successful ship is silent."
        ),
    )


def _render_managed_block(sections: list[AgentInstructionSection]) -> str:
    rendered_sections = "\n".join(section.render() for section in sections).rstrip()
    return f"{MANAGED_AGENTS_START}\n{rendered_sections}\n{MANAGED_AGENTS_END}\n"


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
