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
from envctl_engine.planning.plan_agent.workflow import *
from envctl_engine.planning.plan_agent.terminal_screen import *
from envctl_engine.planning.plan_agent.recovery import *
from envctl_engine.planning.plan_agent.tmux_session import *
import envctl_engine.planning.plan_agent.tmux_workflow_submission_support as tmux_workflow_submission_support

def _launch_plan_agent_tmux_terminals(
    runtime: Any,
    *,
    route: object,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    base_payload: Mapping[str, object],
    prompt_on_existing: bool,
) -> PlanAgentLaunchResult:
    repo_root = Path(runtime.config.base_dir).resolve()
    attach_via = "switch-client" if str(getattr(runtime, "env", {}).get("TMUX", "")).strip() else "attach-session"
    route_flags = getattr(route, "flags", {}) or {}
    create_new_session = bool(route_flags.get("new_session"))
    prompt_existing_possible = not create_new_session and _should_prompt_existing_tmux_session(
        runtime,
        prompt_on_existing=prompt_on_existing,
    )
    existing_attach_target = _find_existing_tmux_attach_target(
        runtime,
        repo_root=repo_root,
        created_worktrees=created_worktrees,
        cli=launch_config.cli,
    )
    unhealthy_existing_reason = str(getattr(runtime, "_last_unhealthy_existing_tmux_session_reason", "") or "")
    unhealthy_existing_outcomes = tuple(getattr(runtime, "_last_unhealthy_existing_tmux_session_outcomes", ()) or ())
    if hasattr(runtime, "_last_unhealthy_existing_tmux_session_reason"):
        try:
            delattr(runtime, "_last_unhealthy_existing_tmux_session_reason")
        except AttributeError:
            pass
    if hasattr(runtime, "_last_unhealthy_existing_tmux_session_outcomes"):
        try:
            delattr(runtime, "_last_unhealthy_existing_tmux_session_outcomes")
        except AttributeError:
            pass
    if existing_attach_target is None and unhealthy_existing_reason:
        return PlanAgentLaunchResult(
            status="failed",
            reason=unhealthy_existing_reason,
            outcomes=unhealthy_existing_outcomes,
            attach_target=None,
        )
    if existing_attach_target is not None:
        if prompt_existing_possible:
            action = _prompt_existing_tmux_session_action(runtime, attach_target=existing_attach_target)
            if action == "attach":
                runtime._emit(
                    "planning.agent_launch.skipped",
                    reason="existing_tmux_session_attach",
                    session_name=existing_attach_target.session_name,
                    attach_command=" ".join(existing_attach_target.attach_command),
                    **base_payload,
                )
                return PlanAgentLaunchResult(
                    status="failed",
                    reason="existing_tmux_session_attach",
                    outcomes=(),
                    attach_target=existing_attach_target,
                )
            create_new_session = True
        attach_command = " ".join(existing_attach_target.attach_command)
        if not create_new_session:
            reason = f"An envctl tmux session already exists for this plan. Attach with: {attach_command}"
            runtime._emit(
                "planning.agent_launch.skipped",
                reason="existing_tmux_session",
                session_name=existing_attach_target.session_name,
                attach_command=attach_command,
                **base_payload,
            )
            return PlanAgentLaunchResult(
                status="failed",
                reason=reason,
                outcomes=(),
                attach_target=PlanAgentAttachTarget(
                    repo_root=existing_attach_target.repo_root,
                    session_name=existing_attach_target.session_name,
                    window_name=existing_attach_target.window_name,
                    attach_via=existing_attach_target.attach_via,
                    attach_command=existing_attach_target.attach_command,
                    new_session_command=_new_session_command_for_route(
                        runtime,
                        route=route,
                        launch_config=launch_config,
                        created_worktrees=created_worktrees,
                    ),
                ),
            )
    runtime._emit(
        "planning.agent_launch.evaluate",
        reason="ready",
        preset=launch_config.preset,
        **base_payload,
    )
    runtime._emit(
        "planning.agent_launch.workflow_selected",
        warning=launch_config.codex_cycles_warning,
        **base_payload,
    )
    outcomes: list[PlanAgentLaunchOutcome] = []
    first_attach_target: PlanAgentAttachTarget | None = None
    for worktree in created_worktrees:
        session_name = _tmux_session_name_for_worktree(repo_root, worktree, cli=launch_config.cli)
        if create_new_session:
            session_name = _next_available_tmux_session_name(runtime, session_name)
        window_name = _tmux_window_name_for_worktree(worktree)
        outcome = _launch_single_tmux_worktree(
            runtime,
            session_name=session_name,
            window_name=window_name,
            launch_config=launch_config,
            workflow=workflow,
            worktree=worktree,
        )
        outcomes.append(outcome)
        if first_attach_target is None and outcome.status == "launched":
            first_attach_target = PlanAgentAttachTarget(
                repo_root=repo_root,
                session_name=session_name,
                window_name=window_name,
                attach_via=attach_via,
                attach_command=_guidance_attach_command(session_name),
            )
    launched = [item for item in outcomes if item.status == "launched"]
    failed = [item for item in outcomes if item.status == "failed"]
    attach_target = first_attach_target or existing_attach_target
    if failed and launched:
        details = _summarize_failed_launch_outcomes(failed)
        suffix = f" Details: {details}." if details else ""
        _print_launch_summary(
            f"Plan agent launch finished with partial success: launched {len(launched)}, failed {len(failed)}.{suffix}"
        )
        return PlanAgentLaunchResult(
            status="partial",
            reason="partial_failure",
            outcomes=tuple(outcomes),
            attach_target=attach_target,
        )
    if failed:
        details = _summarize_failed_launch_outcomes(failed)
        suffix = f" Details: {details}." if details else ""
        _print_launch_summary(f"Plan agent launch failed for {len(failed)} worktree(s).{suffix}")
        return PlanAgentLaunchResult(status="failed", reason="launch_failed", outcomes=tuple(outcomes))
    _print_launch_summary(f"Plan agent launch prepared {len(launched)} tmux session(s).")
    return PlanAgentLaunchResult(
        status="launched",
        reason="launched",
        outcomes=tuple(outcomes),
        attach_target=attach_target,
    )


def _tmux_session_name_for_worktree(repo_root: Path, worktree: CreatedPlanWorktree, *, cli: str) -> str:
    repo_root = Path(repo_root).resolve()
    worktree_root = Path(worktree.root).resolve()
    relative = worktree_root.relative_to(repo_root)
    relative_slug = _sanitize_tmux_name(str(relative), fallback=worktree.name)
    cli_slug = _sanitize_tmux_name(str(cli).strip().lower(), fallback="cli")
    return _sanitize_tmux_name(f"envctl-{repo_root.name}-{relative_slug}-{cli_slug}", fallback="envctl-worktree")


def _next_available_tmux_session_name(runtime: Any, session_name: str) -> str:
    if not _tmux_session_exists(runtime, session_name):
        return session_name
    index = 2
    while True:
        candidate = _sanitize_tmux_name(f"{session_name}-{index}", fallback=session_name)
        if not _tmux_session_exists(runtime, candidate):
            return candidate
        index += 1


def _launch_single_tmux_worktree(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
) -> PlanAgentLaunchOutcome:
    create_error = _ensure_tmux_window(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        worktree=worktree,
    )
    if create_error is not None:
        runtime._emit(
            "planning.agent_launch.failed",
            reason="window_create_failed",
            session_name=session_name,
            window_name=window_name,
            worktree=worktree.name,
            error=create_error,
            transport="tmux",
        )
        return PlanAgentLaunchOutcome(
            worktree_name=worktree.name,
            worktree_root=worktree.root,
            surface_id=None,
            status="failed",
            reason=create_error,
        )
    runtime._emit(
        "planning.agent_launch.surface_created",
        session_name=session_name,
        window_name=window_name,
        worktree=worktree.name,
        source="tmux_window",
        transport="tmux",
    )
    error = _run_tmux_worktree_bootstrap(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
    )
    if error is not None:
        runtime._emit(
            "planning.agent_launch.failed",
            reason="bootstrap_failed",
            session_name=session_name,
            window_name=window_name,
            worktree=worktree.name,
            error=error,
            transport="tmux",
        )
        return PlanAgentLaunchOutcome(
            worktree_name=worktree.name,
            worktree_root=worktree.root,
            surface_id=None,
            status="failed",
            reason=error,
        )
    runtime._emit(
        "planning.agent_launch.command_sent",
        session_name=session_name,
        window_name=window_name,
        worktree=worktree.name,
        preset=launch_config.preset,
        workflow_mode=workflow.mode,
        codex_cycles=workflow.codex_cycles,
        transport="tmux",
    )
    _persist_runtime_events_snapshot(runtime)
    return PlanAgentLaunchOutcome(
        worktree_name=worktree.name,
        worktree_root=worktree.root,
        surface_id=None,
        status="launched",
    )


def _tmux_window_name_for_worktree(worktree: CreatedPlanWorktree) -> str:
    return _sanitize_tmux_name(_tab_title_for_worktree(worktree.name), fallback="implementation")


def _tmux_target(session_name: str, window_name: str) -> str:
    normalized_window = str(window_name).strip()
    if normalized_window.startswith("%"):
        return normalized_window
    if not normalized_window:
        return session_name
    return f"{session_name}:{normalized_window}"


def _enable_tmux_mouse_scrollback(runtime: Any, *, session_name: str) -> str | None:
    result = _run_tmux_probe(
        runtime,
        ("tmux", "set-option", "-t", session_name, "mouse", "on"),
        cwd=Path(runtime.config.base_dir).resolve(),
    )
    if result.returncode == 0:
        return None
    return _tmux_completed_process_error_text(result)


def _wait_for_tmux_window_ready(runtime: Any, *, session_name: str, window_name: str) -> str | None:
    deadline = time.monotonic() + _TMUX_WINDOW_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _tmux_window_exists(runtime, session_name=session_name, window_name=window_name):
            return None
        time.sleep(_TMUX_WINDOW_READY_POLL_INTERVAL_SECONDS)
    return f"tmux_window_unavailable: can't find window: {window_name}"


def _tmux_window_exists(runtime: Any, *, session_name: str, window_name: str) -> bool:
    result = _run_tmux_probe(
        runtime,
        ("tmux", "list-windows", "-t", session_name, "-F", "#{window_name}"),
        cwd=Path(runtime.config.base_dir).resolve(),
    )
    if result.returncode != 0:
        return False
    windows = {str(line).strip() for line in str(getattr(result, "stdout", "")).splitlines() if str(line).strip()}
    return window_name in windows


def _resolve_tmux_attach_target(
    runtime: Any,
    *,
    repo_root: Path,
    session_name: str,
    window_name: str | None,
    attach_via: str,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    cli: str,
) -> PlanAgentAttachTarget | None:
    existing_attach_target = _find_existing_tmux_attach_target(
        runtime,
        repo_root=repo_root,
        created_worktrees=created_worktrees,
        cli=cli,
    )
    if existing_attach_target is not None:
        return existing_attach_target
    if not _tmux_session_exists(runtime, session_name):
        return None
    if window_name and not _tmux_window_exists(runtime, session_name=session_name, window_name=window_name):
        return None
    return PlanAgentAttachTarget(
        repo_root=repo_root,
        session_name=session_name,
        window_name=window_name or "",
        attach_via=attach_via,
        attach_command=_guidance_attach_command(session_name),
    )


def _find_existing_tmux_attach_target(
    runtime: Any,
    *,
    repo_root: Path,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    cli: str,
) -> PlanAgentAttachTarget | None:
    separator = "|||ENVCTL_TMUX_PATH|||"
    targets = [Path(worktree.root).expanduser().resolve(strict=False) for worktree in created_worktrees]
    attach_by_root = {
        Path(worktree.root).expanduser().resolve(strict=False): PlanAgentAttachTarget(
            repo_root=repo_root,
            session_name=_tmux_session_name_for_worktree(repo_root, worktree, cli=cli),
            window_name=_tmux_window_name_for_worktree(worktree),
            attach_via="attach-session",
            attach_command=_guidance_attach_command(_tmux_session_name_for_worktree(repo_root, worktree, cli=cli)),
        )
        for worktree in created_worktrees
    }
    if not targets:
        return None
    for target in targets:
        attach_target = attach_by_root[target]
        session_name = attach_target.session_name
        if not _tmux_session_exists(runtime, session_name):
            continue
        windows_result = _run_tmux_probe(
            runtime,
            ("tmux", "list-windows", "-t", session_name, "-F", f"#{{window_name}}{separator}#{{pane_current_path}}"),
            cwd=Path(runtime.config.base_dir).resolve(),
        )
        if windows_result.returncode != 0:
            continue
        for raw_line in str(getattr(windows_result, "stdout", "")).splitlines():
            window, _, raw_path = raw_line.partition(separator)
            window_name = window.strip()
            normalized_path = raw_path.strip()
            if not window_name or not normalized_path:
                continue
            candidate = Path(normalized_path).expanduser().resolve(strict=False)
            if candidate == target or target in candidate.parents:
                health = _existing_tmux_session_health(
                    runtime,
                    session_name=session_name,
                    window_name=window_name,
                    cli=cli,
                )
                if not health.ready:
                    reason = f"existing_{str(cli).strip().lower() or 'ai'}_session_unhealthy"
                    detail = _format_ai_cli_ready_failure(
                        AiCliReadyResult(ready=False, reason=reason, screen_excerpt=health.screen_excerpt)
                    )
                    setattr(runtime, "_last_unhealthy_existing_tmux_session_reason", reason)
                    setattr(
                        runtime,
                        "_last_unhealthy_existing_tmux_session_outcomes",
                        (
                            PlanAgentLaunchOutcome(
                                worktree_name=next(
                                    (
                                        worktree.name
                                        for worktree in created_worktrees
                                        if Path(worktree.root).expanduser().resolve(strict=False) == target
                                    ),
                                    "",
                                ),
                                worktree_root=target,
                                surface_id=None,
                                status="failed",
                                reason=detail,
                            ),
                        ),
                    )
                    runtime._emit(
                        "planning.agent_launch.existing_session_unhealthy",
                        session_name=session_name,
                        window_name=window_name,
                        cli=cli,
                        reason=detail,
                    )
                    continue
                return PlanAgentAttachTarget(
                    repo_root=repo_root,
                    session_name=session_name,
                    window_name=window_name,
                    attach_via="attach-session",
                    attach_command=_guidance_attach_command(session_name),
                )
    return None


def _existing_tmux_session_looks_healthy(runtime: Any, *, session_name: str, window_name: str, cli: str) -> bool:
    return _existing_tmux_session_health(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cli=cli,
    ).ready


def _existing_tmux_session_health(runtime: Any, *, session_name: str, window_name: str, cli: str) -> AiCliReadyResult:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli not in {"opencode", "codex"}:
        return AiCliReadyResult(ready=True, reason="health_check_not_required")
    screen = _read_tmux_screen(runtime, session_name=session_name, window_name=window_name)
    if not str(screen or "").strip():
        return AiCliReadyResult(ready=False, reason=f"existing_{normalized_cli}_session_empty", screen_excerpt="")
    if _screen_looks_ready(normalized_cli, screen) or _screen_looks_active(normalized_cli, screen):
        return AiCliReadyResult(ready=True, reason="healthy", screen_excerpt=_screen_excerpt(screen))
    return AiCliReadyResult(
        ready=False,
        reason=f"existing_{normalized_cli}_session_unhealthy",
        screen_excerpt=_screen_excerpt(screen),
    )


def _run_tmux_command(
    runtime: Any,
    command: tuple[str, ...],
    *,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    result = _run_tmux_probe(runtime, command, cwd=Path(runtime.config.base_dir).resolve())
    if result.returncode == 0:
        return None
    error = _tmux_completed_process_error_text(result)
    if emit_failure_event:
        runtime._emit(failure_event, reason="tmux_command_failed", command=command[1], error=error)
    return error


def _send_tmux_text(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    text: str,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    return _run_tmux_command(
        runtime,
        ("tmux", "send-keys", "-t", _tmux_target(session_name, window_name), "-l", text),
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
    )


def _send_tmux_key(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    key: str,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    key_name = {"enter": "Enter"}.get(str(key).strip().lower(), key)
    return _run_tmux_command(
        runtime,
        ("tmux", "send-keys", "-t", _tmux_target(session_name, window_name), key_name),
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
    )


def _read_tmux_screen(runtime: Any, *, session_name: str, window_name: str) -> str:
    target = _tmux_target(session_name, window_name)
    for command in (("tmux", "capture-pane", "-p", "-a", "-t", target), ("tmux", "capture-pane", "-p", "-t", target)):
        result = _run_tmux_probe(runtime, command, cwd=Path(runtime.config.base_dir).resolve())
        if result.returncode == 0:
            return str(getattr(result, "stdout", ""))
    return ""


def _run_tmux_existing_session_workflow(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
) -> str | None:
    ready_result = _wait_for_tmux_cli_ready(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cli=launch_config.cli,
    )
    if ready_result is not None and not ready_result.ready:
        return _format_ai_cli_ready_failure(ready_result)
    goal_error = _maybe_submit_tmux_codex_goal(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
        transport="omx",
    )
    if goal_error is not None and goal_error != "codex_goal_ready_timeout":
        return goal_error
    if goal_error is None and launch_config.codex_goal_enable and launch_config.cli == "codex":
        ready_result = _wait_for_tmux_cli_ready(
            runtime,
            session_name=session_name,
            window_name=window_name,
            cli=launch_config.cli,
        )
        if ready_result is not None and not ready_result.ready:
            return _format_ai_cli_ready_failure(ready_result)
    prompt_text, resolution_error = _workflow_step_prompt_text(
        runtime,
        launch_config=launch_config,
        cli=launch_config.cli,
        step=workflow.steps[0],
        worktree=worktree,
    )
    if resolution_error is not None:
        return resolution_error
    prompt_text = _wrap_omx_initial_prompt_for_workflow(prompt_text, workflow=launch_config.omx_workflow)
    submit_error = _submit_tmux_prompt_workflow_step(
        runtime,
        session_name=session_name,
        window_name=window_name,
        prompt_text=prompt_text,
        cli=launch_config.cli,
    )
    if submit_error is not None:
        return submit_error
    queued_steps = workflow.steps[1:]
    if (
        queued_steps
        and launch_config.cli == "codex"
        and (launch_config.transport != "omx" or workflow.codex_cycles > 0)
    ):
        queue_error_reason = _queue_tmux_codex_workflow_steps(
            runtime,
            session_name=session_name,
            window_name=window_name,
            worktree=worktree,
            workflow=workflow,
            queued_steps=queued_steps,
            launch_config=launch_config,
            cli=launch_config.cli,
            transport="omx",
        )
        if queue_error_reason is not None:
            failure_context = _queue_failure_event_context(queue_error_reason)
            runtime._emit(
                "planning.agent_launch.workflow_queue_failed",
                session_name=session_name,
                window_name=window_name,
                worktree=worktree.name,
                cli=launch_config.cli,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
                reason=queue_error_reason,
                transport="omx",
                **failure_context,
            )
            runtime._emit(
                "planning.agent_launch.workflow_fallback",
                session_name=session_name,
                window_name=window_name,
                worktree=worktree.name,
                cli=launch_config.cli,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
                reason=queue_error_reason,
                transport="omx",
                **failure_context,
            )
            return None
    return None


def _maybe_submit_tmux_codex_goal(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
    transport: str,
) -> str | None:
    return tmux_workflow_submission_support.maybe_submit_tmux_codex_goal(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
        transport=transport,
        codex_goal_text_for_worktree_fn=_codex_goal_text_for_worktree,
        submit_tmux_codex_goal_fn=_submit_tmux_codex_goal,
        emit_codex_goal_event_fn=_emit_codex_goal_event,
    )


def _submit_tmux_codex_goal(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    goal_text: str,
) -> str | None:
    return tmux_workflow_submission_support.submit_tmux_codex_goal(
        runtime,
        session_name=session_name,
        window_name=window_name,
        goal_text=goal_text,
        submit_tmux_prompt_workflow_step_fn=_submit_tmux_prompt_workflow_step,
        wait_for_tmux_prompt_ready_after_goal_fn=_wait_for_tmux_prompt_ready_after_goal,
    )


def _wait_for_tmux_prompt_ready_after_goal(runtime: Any, *, session_name: str, window_name: str) -> bool:
    return tmux_workflow_submission_support.wait_for_tmux_prompt_ready_after_goal(
        runtime,
        session_name=session_name,
        window_name=window_name,
        read_tmux_screen_fn=_read_tmux_screen,
    )


def _launch_tmux_cli_bootstrap_commands(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    cwd: Path,
    cli_command: str,
    failure_event: str = "planning.agent_launch.failed",
) -> list[str | None]:
    return tmux_workflow_submission_support.launch_tmux_cli_bootstrap_commands(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cwd=cwd,
        cli_command=cli_command,
        failure_event=failure_event,
        send_tmux_text_fn=_send_tmux_text,
        send_tmux_key_fn=_send_tmux_key,
    )


def _wait_for_tmux_cli_ready(runtime: Any, *, session_name: str, window_name: str, cli: str) -> AiCliReadyResult:
    normalized_cli = str(cli).strip().lower()
    timeout_seconds = _cli_ready_delay_seconds(normalized_cli)
    return tmux_workflow_submission_support.wait_for_tmux_cli_ready(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cli=cli,
        timeout_seconds=timeout_seconds,
        read_tmux_screen_fn=_read_tmux_screen,
    )


def _send_tmux_prompt(runtime: Any, *, session_name: str, window_name: str, text: str) -> str | None:
    target = _tmux_target(session_name, window_name)
    tmux_env = dict(os.environ)
    tmux_env.update(dict(getattr(runtime, "env", {}) or {}))
    load_result = subprocess.run(
        ["tmux", "load-buffer", "-t", target, "-"],
        input=text,
        capture_output=True,
        text=True,
        cwd=Path(runtime.config.base_dir).resolve(),
        env=tmux_env,
        timeout=10.0,
    )
    if load_result.returncode != 0:
        error = (load_result.stderr or "").strip()[:200]
        runtime._emit("planning.agent_launch.failed", reason="tmux_load_buffer_failed", error=error)
        return f"tmux_load_buffer_failed: {error}"
    paste_result = subprocess.run(
        ["tmux", "paste-buffer", "-dpr", "-t", target],
        capture_output=True,
        text=True,
        cwd=Path(runtime.config.base_dir).resolve(),
        env=tmux_env,
        timeout=10.0,
    )
    if paste_result.returncode != 0:
        error = (paste_result.stderr or "").strip()[:200]
        runtime._emit("planning.agent_launch.failed", reason="tmux_paste_buffer_failed", error=error)
        return f"tmux_paste_buffer_failed: {error}"
    return None


def _submit_tmux_prompt_workflow_step(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    prompt_text: str,
    cli: str = "",
) -> str | None:
    return tmux_workflow_submission_support.submit_tmux_prompt_workflow_step(
        runtime,
        session_name=session_name,
        window_name=window_name,
        prompt_text=prompt_text,
        cli=cli,
        send_tmux_prompt_fn=_send_tmux_prompt,
        send_tmux_key_fn=_send_tmux_key,
        wait_for_tmux_prompt_accepted_fn=_wait_for_tmux_prompt_accepted,
        format_ai_cli_ready_failure_fn=_format_ai_cli_ready_failure,
    )


def _wait_for_tmux_prompt_accepted(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    cli: str,
    prompt_text: str,
) -> AiCliReadyResult:
    return tmux_workflow_submission_support.wait_for_tmux_prompt_accepted(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cli=cli,
        prompt_text=prompt_text,
        read_tmux_screen_fn=_read_tmux_screen,
    )


def _run_tmux_worktree_bootstrap(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
) -> str | None:
    send_errors = _launch_tmux_cli_bootstrap_commands(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cwd=worktree.root,
        cli_command=launch_config.cli_command,
    )
    for error in send_errors:
        if error is not None:
            return error
    ready_result = _wait_for_tmux_cli_ready(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cli=launch_config.cli,
    )
    if ready_result is not None and not ready_result.ready:
        return _format_ai_cli_ready_failure(ready_result)
    goal_error = _maybe_submit_tmux_codex_goal(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
        transport="tmux",
    )
    if goal_error is not None and goal_error != "codex_goal_ready_timeout":
        return goal_error
    if goal_error is None and launch_config.codex_goal_enable and launch_config.cli == "codex":
        ready_result = _wait_for_tmux_cli_ready(
            runtime,
            session_name=session_name,
            window_name=window_name,
            cli=launch_config.cli,
        )
        if ready_result is not None and not ready_result.ready:
            return _format_ai_cli_ready_failure(ready_result)
    prompt_text, resolution_error = _workflow_step_prompt_text(
        runtime,
        launch_config=launch_config,
        cli=launch_config.cli,
        step=workflow.steps[0],
        worktree=worktree,
    )
    if resolution_error is not None:
        return resolution_error
    submit_error = _submit_tmux_prompt_workflow_step(
        runtime,
        session_name=session_name,
        window_name=window_name,
        prompt_text=prompt_text,
        cli=launch_config.cli,
    )
    if submit_error is not None:
        return submit_error
    queued_steps = workflow.steps[1:]
    if queued_steps and launch_config.cli == "codex":
        queue_error_reason = _queue_tmux_codex_workflow_steps(
            runtime,
            session_name=session_name,
            window_name=window_name,
            worktree=worktree,
            workflow=workflow,
            queued_steps=queued_steps,
            launch_config=launch_config,
            cli=launch_config.cli,
            transport="tmux",
        )
        if queue_error_reason is not None:
            failure_context = _queue_failure_event_context(queue_error_reason)
            runtime._emit(
                "planning.agent_launch.workflow_queue_failed",
                session_name=session_name,
                window_name=window_name,
                worktree=worktree.name,
                cli=launch_config.cli,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
                reason=queue_error_reason,
                transport="tmux",
                **failure_context,
            )
            runtime._emit(
                "planning.agent_launch.workflow_fallback",
                session_name=session_name,
                window_name=window_name,
                worktree=worktree.name,
                cli=launch_config.cli,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
                reason=queue_error_reason,
                transport="tmux",
                **failure_context,
            )
            return None
    return None


def _queue_tmux_codex_workflow_steps(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    worktree: CreatedPlanWorktree,
    workflow: _PlanAgentWorkflow,
    queued_steps: tuple[_PlanAgentWorkflowStep, ...],
    launch_config: PlanAgentLaunchConfig,
    cli: str,
    transport: str = "tmux",
) -> str | None:
    return tmux_workflow_submission_support.queue_tmux_codex_workflow_steps(
        runtime,
        session_name=session_name,
        window_name=window_name,
        worktree=worktree,
        workflow=workflow,
        queued_steps=queued_steps,
        launch_config=launch_config,
        cli=cli,
        transport=transport,
        codex_goal_text_for_worktree_fn=_codex_goal_text_for_worktree,
        workflow_step_prompt_text_fn=_workflow_step_prompt_text,
        send_tmux_prompt_fn=_send_tmux_prompt,
        queue_tmux_codex_message_fn=_queue_tmux_codex_message,
    )


def _queue_tmux_codex_message(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    text: str,
    require_text_match: bool = True,
) -> bool:
    return tmux_workflow_submission_support.queue_tmux_codex_message(
        runtime,
        session_name=session_name,
        window_name=window_name,
        text=text,
        require_text_match=require_text_match,
        read_tmux_screen_fn=_read_tmux_screen,
        send_tmux_key_fn=_send_tmux_key,
    )


def attach_plan_agent_terminal(runtime: Any, attach_target: PlanAgentAttachTarget) -> int:
    if attach_target.attach_via == "switch-client":
        result = _run_tmux_probe(
            runtime,
            ("tmux", "switch-client", "-t", attach_target.session_name),
            cwd=attach_target.repo_root,
        )
        if result.returncode != 0:
            print(_tmux_completed_process_error_text(result), file=sys.stderr)
            return 1
        return 0
    return _attach_interactive(runtime, attach_target.attach_command, cwd=attach_target.repo_root)


def _ensure_tmux_window(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> str | None:
    cwd = Path(worktree.root).resolve()
    shell_command = launch_config.shell
    if _tmux_session_exists(runtime, session_name):
        command = (
            "tmux",
            "new-window",
            "-d",
            "-t",
            session_name,
            "-n",
            window_name,
            "-c",
            str(cwd),
            shell_command,
        )
    else:
        command = (
            "tmux",
            "new-session",
            "-d",
            "-s",
            session_name,
            "-n",
            window_name,
            "-c",
            str(cwd),
            shell_command,
        )
    result = _run_tmux_probe(runtime, command, cwd=Path(runtime.config.base_dir).resolve())
    if result.returncode == 0:
        option_error = _enable_tmux_mouse_scrollback(runtime, session_name=session_name)
        if option_error is not None:
            return option_error
        wait_error = _wait_for_tmux_window_ready(runtime, session_name=session_name, window_name=window_name)
        if wait_error is None:
            return None
        return wait_error
    return _tmux_completed_process_error_text(result)


__all__ = tuple(name for name in globals() if not name.startswith("__"))
