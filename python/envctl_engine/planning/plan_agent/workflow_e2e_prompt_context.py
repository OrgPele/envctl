from __future__ import annotations

from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree
from envctl_engine.planning.plan_agent.workflow_build import _browser_e2e_instruction_text
from envctl_engine.planning.plan_agent.workflow_runtime_addresses import _runtime_addresses_prompt_section


def _shape_queue_message_text(runtime: Any, text: str, *, worktree: CreatedPlanWorktree | None = None) -> str:
    if str(text).strip() != _browser_e2e_instruction_text().strip():
        return text
    sections = [
        section
        for section in (
            _original_task_source_prompt_section(runtime, worktree=worktree),
            _runtime_addresses_prompt_section(runtime, worktree=worktree),
        )
        if section
    ]
    if not sections:
        return text
    return f"{str(text).rstrip()}\n\n" + "\n\n".join(sections) + "\n"


def _original_task_source_prompt_section(
    runtime: Any,
    *,
    worktree: CreatedPlanWorktree | None,
) -> str:
    if worktree is None:
        return ""
    plan_path = _original_plan_file_path(runtime, str(worktree.plan_file or ""))
    main_task_path = Path(worktree.root) / "MAIN_TASK.md"
    lines = [
        "## Original task source for E2E validation",
        "MAIN_TASK.md may be rewritten by cycle prompts. Use this original plan file before the current "
        "MAIN_TASK.md when validating the end-to-end requirement.",
    ]
    if plan_path is not None:
        lines.append(f'- Original plan file: "{plan_path}"')
    lines.append(f'- Seeded worktree task file: "{main_task_path}"')
    return "\n".join(lines)


def _original_plan_file_path(runtime: Any, plan_file: str) -> Path | None:
    normalized = str(plan_file or "").strip()
    if not normalized:
        return None
    raw_path = Path(normalized).expanduser()
    if raw_path.is_absolute():
        return raw_path
    planning_dir = Path(getattr(getattr(runtime, "config", None), "planning_dir", "todo/plans"))
    return (planning_dir / raw_path).resolve()


__all__ = tuple(name for name in globals() if not name.startswith("__"))
