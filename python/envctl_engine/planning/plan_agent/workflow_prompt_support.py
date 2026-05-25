from __future__ import annotations

from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.constants import _PROMPT_SHAPING_COMMAND_TOKEN_RE
from envctl_engine.planning.plan_agent.launch_policy import uses_direct_submission
from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflowStep,
)
from envctl_engine.planning.plan_agent.workflow_build import _browser_e2e_instruction_text, _slash_command
from envctl_engine.runtime.prompt_install_support import (
    resolve_codex_direct_prompt_body,
    resolve_opencode_direct_prompt_body,
)
from envctl_engine.runtime.runtime_context import optional_state_repository as optional_state_repository
from envctl_engine.planning.plan_agent.workflow_runtime_addresses import (
    _append_runtime_addresses_for_preset as _append_runtime_addresses_for_preset,
    _component_port as _component_port,
    _dependency_address as _dependency_address,
    _dependency_address_lines as _dependency_address_lines,
    _dependency_label as _dependency_label,
    _int_or_none as _int_or_none,
    _latest_runtime_state as _latest_runtime_state,
    _runtime_addresses_prompt_section as _runtime_addresses_prompt_section,
    _service_address_lines as _service_address_lines,
    _state_project_matches_worktree as _state_project_matches_worktree,
    _state_service_matches_worktree as _state_service_matches_worktree,
)


def _workflow_step_prompt_text(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    cli: str,
    step: _PlanAgentWorkflowStep,
    worktree: CreatedPlanWorktree | None = None,
) -> tuple[str, str | None]:
    if step.kind not in {"submit_direct_prompt", "queue_direct_prompt"}:
        return _shape_queue_message_text(runtime, step.text, worktree=worktree), None
    return _resolve_preset_submission_text(
        runtime,
        launch_config=launch_config,
        cli=cli,
        preset=step.text,
        worktree=worktree,
    )


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


def _resolve_preset_submission_text(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    cli: str,
    preset: str,
    arguments: str = "",
    worktree: CreatedPlanWorktree | None = None,
) -> tuple[str, str | None]:
    normalized_cli = str(cli).strip().lower()
    direct_prompt = uses_direct_submission(
        cli=normalized_cli,
        direct_prompt_enabled=launch_config.direct_prompt_enabled,
    )
    try:
        if not direct_prompt:
            resolved = _slash_command(cli, preset, arguments=arguments)
        elif normalized_cli == "codex":
            resolved = resolve_codex_direct_prompt_body(
                preset=preset,
                env=getattr(runtime, "env", {}),
                arguments=arguments,
            )
        elif normalized_cli == "opencode":
            resolved = resolve_opencode_direct_prompt_body(
                preset=preset,
                env=getattr(runtime, "env", {}),
                arguments=arguments,
            )
        else:
            resolved = _slash_command(cli, preset, arguments=arguments)
    except (LookupError, OSError, ValueError) as exc:
        return "", f"prompt_resolution_failed: {exc}"
    if direct_prompt:
        resolved = _append_runtime_addresses_for_preset(
            runtime,
            preset=preset,
            prompt_text=resolved,
            worktree=worktree,
        )
    return _shape_prompt_text(
        resolved,
        direct_prompt=direct_prompt,
        ulw_loop_prefix=launch_config.ulw_loop_prefix,
        ulw_suffix=launch_config.ulw_suffix,
    )


def _shape_prompt_text(
    text: str,
    *,
    direct_prompt: bool,
    ulw_loop_prefix: bool,
    ulw_suffix: bool,
) -> tuple[str, str | None]:
    shaped = str(text)
    stripped = shaped.strip()
    if ulw_loop_prefix:
        if not direct_prompt:
            return "", "prompt_resolution_failed: ulw_loop_prefix_requires_direct_prompt"
        slash_command_tokens = [
            token
            for token in str(stripped).split()
            if _PROMPT_SHAPING_COMMAND_TOKEN_RE.fullmatch(token)
        ]
        if any(token != "/ulw-loop" for token in slash_command_tokens):
            return "", "prompt_resolution_failed: multiple_slash_commands_not_allowed"
        if not stripped.startswith("/ulw-loop"):
            shaped = f"/ulw-loop {stripped}" if stripped else "/ulw-loop"
            stripped = shaped.strip()
    if ulw_suffix and not stripped.endswith(" ulw") and stripped != "ulw":
        shaped = f"{shaped.rstrip()} ulw" if shaped.rstrip() else "ulw"
    return shaped, None


__all__ = tuple(name for name in globals() if not name.startswith("__"))
