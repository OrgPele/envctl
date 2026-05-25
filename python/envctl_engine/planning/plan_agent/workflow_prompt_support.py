from __future__ import annotations

from collections.abc import Mapping
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
from envctl_engine.runtime.runtime_context import optional_state_repository
from envctl_engine.state.models import RunState


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


def _append_runtime_addresses_for_preset(
    runtime: Any,
    *,
    preset: str,
    prompt_text: str,
    worktree: CreatedPlanWorktree | None = None,
) -> str:
    if str(preset).strip() != "implement_task":
        return prompt_text
    context = _runtime_addresses_prompt_section(runtime, worktree=worktree)
    if not context:
        return prompt_text
    return f"{prompt_text.rstrip()}\n\n{context}\n"


def _runtime_addresses_prompt_section(runtime: Any, *, worktree: CreatedPlanWorktree | None = None) -> str:
    state = _latest_runtime_state(runtime)
    if state is None:
        return ""
    lines = [
        "## Current envctl runtime addresses",
        "Use these currently known localhost addresses when validating or debugging. "
        "They are generated from saved envctl runtime state; verify them again if you restart services.",
    ]
    dependency_lines = _dependency_address_lines(state, worktree=worktree)
    service_lines = _service_address_lines(state, worktree=worktree)
    if dependency_lines:
        lines.append("Dependencies:")
        lines.extend(f"- {line}" for line in dependency_lines)
    if service_lines:
        lines.append("Backend/frontend:")
        lines.extend(f"- {line}" for line in service_lines)
    if len(lines) == 2:
        return ""
    return "\n".join(lines)


def _latest_runtime_state(runtime: Any) -> RunState | None:
    state_repository = optional_state_repository(runtime)
    if state_repository is not None and hasattr(state_repository, "load_latest"):
        try:
            state = state_repository.load_latest()
        except Exception:
            state = None
        if isinstance(state, RunState):
            return state
    try_loader = getattr(runtime, "_try_load_existing_state", None)
    if callable(try_loader):
        for mode in ("trees", "main"):
            try:
                state = try_loader(mode=mode, strict_mode_match=True)
            except Exception:
                state = None
            if isinstance(state, RunState):
                return state
    return None


def _dependency_address_lines(state: RunState, *, worktree: CreatedPlanWorktree | None = None) -> list[str]:
    rows: list[str] = []
    seen: set[tuple[str, int]] = set()
    for project_name, requirements in state.requirements.items():
        if not _state_project_matches_worktree(project_name, worktree):
            continue
        for dependency_id in ("postgres", "redis", "supabase", "n8n"):
            component = requirements.component(dependency_id)
            if not bool(component.get("enabled", False)):
                continue
            port = _component_port(component)
            if port is None:
                continue
            key = (dependency_id, port)
            if key in seen:
                continue
            seen.add(key)
            address = _dependency_address(dependency_id, port)
            rows.append(f"{_dependency_label(dependency_id)} ({project_name}): {address}")
    return rows


def _service_address_lines(state: RunState, *, worktree: CreatedPlanWorktree | None = None) -> list[str]:
    rows: list[str] = []
    for service in state.services.values():
        if not _state_service_matches_worktree(service, worktree):
            continue
        service_type = str(service.type or "").strip().lower()
        if service_type not in {"backend", "frontend"}:
            continue
        port = service.actual_port or service.requested_port
        if port is None:
            continue
        label = "Backend" if service_type == "backend" else "Frontend"
        rows.append(f"{label} ({service.name}): http://localhost:{int(port)}")
    return rows


def _state_project_matches_worktree(project_name: object, worktree: CreatedPlanWorktree | None) -> bool:
    if worktree is None:
        return True
    normalized_project = str(project_name or "").strip().casefold()
    normalized_worktree = str(worktree.name or "").strip().casefold()
    if normalized_project == normalized_worktree:
        return True
    return bool(normalized_project and normalized_worktree.startswith(f"{normalized_project}-"))


def _state_service_matches_worktree(service: object, worktree: CreatedPlanWorktree | None) -> bool:
    if worktree is None:
        return True
    service_name = str(getattr(service, "name", "") or "").strip()
    worktree_name = str(worktree.name or "").strip()
    if worktree_name and service_name.casefold().startswith(f"{worktree_name.casefold()} "):
        return True
    cwd_raw = str(getattr(service, "cwd", "") or "").strip()
    if not cwd_raw:
        return False
    try:
        cwd = Path(cwd_raw).expanduser().resolve(strict=False)
        root = Path(worktree.root).expanduser().resolve(strict=False)
    except OSError:
        return False
    return cwd == root or root in cwd.parents


def _component_port(component: Mapping[str, object]) -> int | None:
    for key in ("final", "actual", "requested"):
        port = _int_or_none(component.get(key))
        if port is not None and port > 0:
            return port
    resources = component.get("resources")
    if isinstance(resources, Mapping):
        port = _int_or_none(resources.get("primary"))
        if port is not None and port > 0:
            return port
    return None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _dependency_label(dependency_id: str) -> str:
    return {"postgres": "Postgres", "redis": "Redis", "supabase": "Supabase", "n8n": "n8n"}.get(
        dependency_id,
        dependency_id,
    )


def _dependency_address(dependency_id: str, port: int) -> str:
    if dependency_id == "redis":
        return f"redis://localhost:{port}"
    if dependency_id in {"supabase", "n8n"}:
        return f"http://localhost:{port}"
    return f"localhost:{port}"


__all__ = tuple(name for name in globals() if not name.startswith("__"))
