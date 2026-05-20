from __future__ import annotations

# ruff: noqa: F401,F403,F405
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from importlib import resources
from pathlib import Path
from typing import Any, Literal, Mapping

from envctl_engine.planning import planning_feature_name
from envctl_engine.config import EngineConfig, _apply_plan_agent_aliases
from envctl_engine.runtime.codex_tmux_support import (
    _attach_interactive,
    _completed_process_error_text as _tmux_completed_process_error_text,
    _run_probe as _run_tmux_probe,
    _sanitize_name as _sanitize_tmux_name,
    _tmux_session_exists,
)
from envctl_engine.runtime.prompt_install_support import (
    resolve_codex_direct_prompt_body,
    resolve_opencode_direct_prompt_body,
)
from envctl_engine.state.models import RunState
from envctl_engine.shared.parsing import parse_bool, parse_int_or_none

from envctl_engine.planning.plan_agent.constants import *
from envctl_engine.planning.plan_agent.models import *
from envctl_engine.planning.plan_agent.config import *
from envctl_engine.planning.plan_agent.terminal_screen import *

def _build_plan_agent_workflow(
    *,
    cli: str,
    preset: str,
    codex_cycles: int,
    direct_prompt_enabled: bool = False,
    browser_e2e_followup_enable: bool = True,
    pr_review_comments_followup_enable: bool = True,
) -> _PlanAgentWorkflow:
    normalized_cli = str(cli).strip().lower()
    bounded_cycles = max(0, min(int(codex_cycles), _PLAN_AGENT_CODEX_CYCLE_CAP))
    if _uses_direct_submission(cli=normalized_cli, direct_prompt_enabled=direct_prompt_enabled):
        initial_step = _PlanAgentWorkflowStep(kind="submit_direct_prompt", text=str(preset).strip())
    else:
        initial_step = _PlanAgentWorkflowStep(kind="submit_prompt", text=_slash_command(cli, preset))
    if normalized_cli != "codex" or bounded_cycles <= 0:
        steps = [initial_step]
        if normalized_cli == "codex":
            if browser_e2e_followup_enable:
                steps.append(_PlanAgentWorkflowStep(kind="queue_message", text=_browser_e2e_instruction_text()))
            if pr_review_comments_followup_enable:
                steps.append(
                    _PlanAgentWorkflowStep(kind="queue_message", text=_pr_review_comments_instruction_text())
                )
        return _PlanAgentWorkflow(
            mode=_PLAN_AGENT_WORKFLOW_SINGLE_PROMPT,
            codex_cycles=bounded_cycles,
            steps=tuple(steps),
        )
    steps = [_PlanAgentWorkflowStep(kind="submit_direct_prompt", text="implement_task")]
    for cycle in range(1, bounded_cycles + 1):
        if cycle == bounded_cycles:
            steps.append(_PlanAgentWorkflowStep(kind="queue_direct_prompt", text="finalize_task"))
            if browser_e2e_followup_enable:
                steps.append(_PlanAgentWorkflowStep(kind="queue_message", text=_browser_e2e_instruction_text()))
            if pr_review_comments_followup_enable:
                steps.append(
                    _PlanAgentWorkflowStep(kind="queue_message", text=_pr_review_comments_instruction_text())
                )
            continue
        if cycle == 1:
            completion_text = _first_cycle_completion_instruction_text()
        else:
            completion_text = _intermediate_cycle_completion_instruction_text()
        steps.append(_PlanAgentWorkflowStep(kind="queue_message", text=completion_text))
        steps.append(_PlanAgentWorkflowStep(kind="queue_direct_prompt", text="continue_task"))
        steps.append(_PlanAgentWorkflowStep(kind="queue_direct_prompt", text="implement_task"))
    return _PlanAgentWorkflow(
        mode=_PLAN_AGENT_WORKFLOW_CODEX_CYCLES,
        codex_cycles=bounded_cycles,
        steps=tuple(steps),
    )


def _finalization_instruction_text() -> str:
    return _load_plan_agent_followup_prompt(_FINALIZATION_INSTRUCTION_TEMPLATE)


def _first_cycle_completion_instruction_text() -> str:
    return _load_plan_agent_followup_prompt(_FIRST_CYCLE_COMPLETION_TEMPLATE)


def _intermediate_cycle_completion_instruction_text() -> str:
    return _load_plan_agent_followup_prompt(_INTERMEDIATE_CYCLE_COMPLETION_TEMPLATE)


def _browser_e2e_instruction_text() -> str:
    return _load_plan_agent_followup_prompt(_BROWSER_E2E_FOLLOWUP_TEMPLATE)


def _pr_review_comments_instruction_text() -> str:
    return _load_plan_agent_followup_prompt(_PR_REVIEW_COMMENTS_FOLLOWUP_TEMPLATE)


def _load_plan_agent_followup_prompt(name: str) -> str:
    template_name = f"{str(name).strip()}.md"
    template_file = resources.files(_PROMPT_TEMPLATE_PACKAGE).joinpath(template_name)
    if not template_file.is_file():
        raise LookupError(f"Missing plan-agent follow-up prompt template: {template_name}")
    body = template_file.read_text(encoding="utf-8").strip()
    if not body:
        raise ValueError(f"Plan-agent follow-up prompt template is empty: {template_name}")
    return body


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
    direct_prompt = _uses_direct_submission(
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
    state_repository = getattr(runtime, "state_repository", None)
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


def _surface_respawn_command(launch_config: PlanAgentLaunchConfig, worktree: CreatedPlanWorktree) -> str:
    _ = worktree
    return launch_config.shell


def _wrap_omx_initial_prompt_for_workflow(text: str, *, workflow: str) -> str:
    normalized_workflow = str(workflow or "").strip().lower()
    if normalized_workflow not in _OMX_WORKFLOW_KEYWORDS:
        return text
    stripped = str(text).lstrip()
    prefix = f"${normalized_workflow}"
    if stripped == prefix or stripped.startswith(f"{prefix} ") or stripped.startswith(f"{prefix}\n"):
        return text
    return f"{prefix}\n\n{text}"


def _codex_goal_text_for_worktree(
    *,
    worktree: CreatedPlanWorktree,
    preset: str,
    workflow_mode: str,
    omx_workflow: str,
) -> str:
    plan_selector = str(worktree.plan_file or "").strip() or str(worktree.name).strip() or "selected plan"
    lines = [
        f"Implement the envctl plan-agent task for {plan_selector} in this worktree.",
        "Authoritative source: MAIN_TASK.md in the current worktree.",
        f"Initial preset: {str(preset).strip() or _DEFAULT_PRESET}.",
        f"Workflow mode: {str(workflow_mode).strip() or _PLAN_AGENT_WORKFLOW_SINGLE_PROMPT}.",
    ]
    normalized_omx = str(omx_workflow or "").strip().lower()
    if normalized_omx:
        lines.append(f"OMX workflow: ${normalized_omx}; keep its completion contract active after this goal frame.")
    lines.append("Complete the implementation, run relevant tests, commit, and open/update the PR when green.")
    return " ".join(lines)


def _emit_codex_goal_event(
    runtime: Any,
    event: str,
    *,
    cli: str,
    workflow: _PlanAgentWorkflow,
    transport: str,
    worktree: CreatedPlanWorktree,
    reason: str | None = None,
    **target: object,
) -> None:
    payload: dict[str, object] = {
        **target,
        "worktree": worktree.name,
        "cli": cli,
        "workflow_mode": workflow.mode,
        "codex_cycles": workflow.codex_cycles,
        "transport": transport,
    }
    if reason is not None:
        payload["reason"] = reason
    runtime._emit(event, **payload)


def _tab_title_for_worktree(name: str) -> str:
    normalized = str(name).strip()
    if not normalized:
        return "implementation"
    parts = [part.strip() for part in normalized.split("_") if str(part).strip()]
    if len(parts) < 4:
        return normalized
    tail_parts: list[str] = []
    for part in reversed(parts[1:]):
        if len(tail_parts) >= 3:
            break
        if part in _LOW_SIGNAL_TAB_TITLE_WORDS:
            continue
        tail_parts.append(part)
    tail_parts.reverse()
    candidate = "_".join([parts[0], *tail_parts]) if tail_parts else normalized
    if len(candidate) <= _PLAN_AGENT_TAB_TITLE_MAX_LEN:
        return candidate
    fallback_tail = tail_parts[-2:] if tail_parts else parts[-2:]
    fallback = "_".join([parts[0], *fallback_tail])
    return fallback or candidate or normalized


def _review_prompt_arguments(
    *,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None,
    original_plan_path: Path | None,
) -> str:
    parts = [f'Project: {project_name}']
    if review_bundle_path is not None:
        parts.append(f'Review bundle: "{review_bundle_path}"')
    parts.append(f'Worktree directory: "{project_root}"')
    if original_plan_path is not None:
        parts.append(f'Original plan file: "{original_plan_path}"')
    return "\n".join(str(part).strip() for part in parts if str(part).strip())


def _review_original_plan_path(project_name: str, project_root: Path, *, repo_root: Path) -> Path | None:
    recorded_plan = _recorded_plan_file_from_worktree(project_root)
    resolved = _resolve_recorded_plan_file(Path(repo_root), recorded_plan)
    if resolved is not None:
        return resolved
    if recorded_plan:
        return None
    return _infer_plan_file_from_feature(Path(repo_root), feature_name=_feature_name_from_project_name(project_name))


def _recorded_plan_file_from_worktree(project_root: Path) -> str:
    provenance_path = Path(project_root) / _WORKTREE_PROVENANCE_PATH
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(provenance, dict):
        return ""
    return str(provenance.get("plan_file", "")).strip()


def _resolve_recorded_plan_file(repo_root: Path, recorded_plan: str) -> Path | None:
    normalized_plan = str(recorded_plan or "").strip()
    if not normalized_plan:
        return None
    normalized = Path(normalized_plan.replace("\\", "/").lstrip("./"))
    for root in (_PLANNING_ROOT, _DONE_PLANNING_ROOT):
        candidate = repo_root / root / normalized
        if candidate.is_file():
            return candidate.resolve()
    return None


def _feature_name_from_project_name(project_name: str) -> str:
    normalized = str(project_name).strip()
    return re.sub(r"-\d+$", "", normalized)


def _infer_plan_file_from_feature(repo_root: Path, *, feature_name: str) -> Path | None:
    normalized_feature = str(feature_name).strip()
    if not normalized_feature:
        return None
    active_matches = _plan_matches_for_feature(repo_root / _PLANNING_ROOT, feature_name=normalized_feature)
    if len(active_matches) == 1:
        return active_matches[0]
    if active_matches:
        return None
    archived_matches = _plan_matches_for_feature(repo_root / _DONE_PLANNING_ROOT, feature_name=normalized_feature)
    if len(archived_matches) == 1:
        return archived_matches[0]
    return None


def _plan_matches_for_feature(planning_root: Path, *, feature_name: str) -> list[Path]:
    if not planning_root.is_dir():
        return []
    matches: list[Path] = []
    for candidate in sorted(planning_root.glob("*/*.md")):
        if candidate.name == "README.md":
            continue
        relative = candidate.relative_to(planning_root)
        if planning_feature_name(str(relative).replace("\\", "/")) != feature_name:
            continue
        matches.append(candidate.resolve())
    return matches


def _active_plan_selector_for_path(*, repo_root: Path, plan_path: Path) -> str | None:
    planning_root = repo_root / _PLANNING_ROOT
    try:
        selector = str(plan_path.relative_to(planning_root)).replace("\\", "/")
    except ValueError:
        return None
    selector = selector.strip()
    if not selector:
        return None
    return selector


def resolve_plan_agent_launch_command(
    *,
    project_name: str,
    project_root: Path,
    repo_root: Path,
    envctl_executable: str = "envctl",
) -> str | None:
    plan_path = _review_original_plan_path(project_name, project_root, repo_root=repo_root)
    selector = (
        _active_plan_selector_for_path(repo_root=repo_root, plan_path=plan_path)
        if plan_path is not None
        else None
    )
    if not selector and _recorded_plan_file_from_worktree(project_root):
        return None
    if not selector:
        selector = f"{_feature_name_from_project_name(project_name)}.md"
    return " ".join(
        (
            shlex.quote(envctl_executable),
            "--repo",
            shlex.quote(_cli_display_path(repo_root)),
            "--plan",
            shlex.quote(selector),
            "--tmux",
            "--opencode",
            "--headless",
            "--new-session",
        )
    )


def _cli_display_path(path: Path) -> str:
    raw = str(path)
    if raw.startswith("/private/var/"):
        return raw.removeprefix("/private")
    return raw


def _slash_command(cli: str, preset: str, *, arguments: str = "") -> str:
    normalized = str(preset).strip()
    if not normalized:
        normalized = _DEFAULT_PRESET
    trimmed = normalized[1:] if normalized.startswith("/") else normalized
    if str(cli).strip().lower() == "codex":
        if trimmed.startswith("prompts:"):
            command = f"/{trimmed}"
        else:
            command = f"/prompts:{trimmed}"
    else:
        command = normalized if normalized.startswith("/") else f"/{normalized}"
    extra = str(arguments).strip()
    if not extra:
        return command
    return f"{command} {extra}"


__all__ = tuple(name for name in globals() if not name.startswith("__"))
