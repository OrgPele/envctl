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

def review_agent_launch_readiness(runtime: Any) -> ReviewAgentLaunchReadiness:
    launch_config = resolve_plan_agent_launch_config(runtime.config, getattr(runtime, "env", {}))
    if launch_config.transport == "superset":
        return ReviewAgentLaunchReadiness(
            ready=False,
            reason="unsupported_superset_review_tab",
            cli=launch_config.cli,
        )
    missing_commands = tuple(_missing_launch_commands(runtime, launch_config))
    if missing_commands:
        return ReviewAgentLaunchReadiness(
            ready=False,
            reason="missing_executables",
            cli=launch_config.cli,
            missing=missing_commands,
        )
    if launch_config.cmux_workspace:
        return ReviewAgentLaunchReadiness(ready=True, reason="ready", cli=launch_config.cli)
    if _default_target_workspace_title(runtime, launch_config, workspace_mode="reviews"):
        return ReviewAgentLaunchReadiness(ready=True, reason="ready", cli=launch_config.cli)
    reason = (
        "missing_cmux_context"
        if _missing_required_cmux_context(runtime, launch_config)
        else "workspace_unavailable"
    )
    return ReviewAgentLaunchReadiness(ready=False, reason=reason, cli=launch_config.cli)


def launch_review_agent_terminal(
    runtime: Any,
    *,
    repo_root: Path,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None = None,
) -> AgentTerminalLaunchResult:
    launch_config = resolve_plan_agent_launch_config(runtime.config, getattr(runtime, "env", {}))
    if launch_config.transport == "superset":
        runtime._emit(
            "dashboard.review_tab.failed",
            reason="unsupported_superset_review_tab",
            project=project_name,
            cli=launch_config.cli,
        )
        return AgentTerminalLaunchResult(status="failed", reason="unsupported_superset_review_tab")
    missing_commands = _missing_launch_commands(runtime, launch_config)
    if missing_commands:
        runtime._emit(
            "dashboard.review_tab.failed",
            reason="missing_executables",
            project=project_name,
            cli=launch_config.cli,
            missing=missing_commands,
        )
        return AgentTerminalLaunchResult(status="failed", reason="missing_executables")
    workspace_target = _ensure_workspace_id(
        runtime,
        launch_config,
        workspace_mode="reviews",
        event_prefix="dashboard.review_tab",
    )
    if workspace_target is None:
        reason = (
            "missing_cmux_context"
            if _missing_required_cmux_context(runtime, launch_config)
            else "workspace_unavailable"
        )
        runtime._emit(
            "dashboard.review_tab.failed",
            reason=reason,
            project=project_name,
            cli=launch_config.cli,
        )
        return AgentTerminalLaunchResult(status="failed", reason=reason)
    workspace_id = workspace_target.workspace_id
    surface_id, create_error = _create_surface(runtime, workspace_id=workspace_id)
    if create_error or surface_id is None:
        runtime._emit(
            "dashboard.review_tab.failed",
            reason="surface_create_failed",
            project=project_name,
            workspace_id=workspace_id,
            error=create_error,
            cli=launch_config.cli,
        )
        return AgentTerminalLaunchResult(status="failed", reason=create_error or "surface_create_failed")
    runtime._emit(
        "dashboard.review_tab.surface_created",
        project=project_name,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
    )
    _start_background_review_surface_bootstrap(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        launch_config=launch_config,
        repo_root=repo_root,
        project_name=project_name,
        project_root=project_root,
        review_bundle_path=review_bundle_path,
    )
    runtime._emit(
        "dashboard.review_tab.launched",
        project=project_name,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
    )
    _print_launch_summary(f"Opened origin review tab for {project_name}.")
    return AgentTerminalLaunchResult(status="launched", reason="launched", surface_id=surface_id)


def _launch_single_worktree(
    runtime: Any,
    *,
    workspace_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
    starter_surface_id: str | None = None,
) -> PlanAgentLaunchOutcome:
    surface_source = "starter_reused" if starter_surface_id else "new_surface"
    if starter_surface_id:
        surface_id = starter_surface_id
        create_error = None
    else:
        surface_id, create_error = _create_surface(runtime, workspace_id=workspace_id)
    if create_error or surface_id is None:
        runtime._emit(
            "planning.agent_launch.failed",
            reason="surface_create_failed",
            workspace_id=workspace_id,
            worktree=worktree.name,
            error=create_error,
        )
        return PlanAgentLaunchOutcome(
            worktree_name=worktree.name,
            worktree_root=worktree.root,
            surface_id=None,
            status="failed",
            reason=create_error or "surface_create_failed",
        )
    runtime._emit(
        "planning.agent_launch.surface_created",
        workspace_id=workspace_id,
        surface_id=surface_id,
        worktree=worktree.name,
        source=surface_source,
    )
    _start_background_surface_bootstrap(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        launch_config=launch_config,
        worktree=worktree,
    )
    return PlanAgentLaunchOutcome(
        worktree_name=worktree.name,
        worktree_root=worktree.root,
        surface_id=surface_id,
        status="launched",
    )


def _create_surface(runtime: Any, *, workspace_id: str) -> tuple[str | None, str | None]:
    result = runtime.process_runner.run(
        ["cmux", "new-surface", "--workspace", workspace_id],
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(result, "returncode", 1) != 0:
        return None, _completed_process_error_text(result)
    return _surface_id_from_output(str(getattr(result, "stdout", ""))), None


def _start_background_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> None:
    thread = threading.Thread(
        target=_complete_surface_bootstrap,
        kwargs={
            "runtime": runtime,
            "workspace_id": workspace_id,
            "surface_id": surface_id,
            "launch_config": launch_config,
            "worktree": worktree,
        },
        name=f"envctl-plan-agent-{worktree.name}",
        daemon=False,
    )
    thread.start()


def _start_background_review_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    repo_root: Path,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None,
) -> None:
    thread = threading.Thread(
        target=_complete_review_surface_bootstrap,
        kwargs={
            "runtime": runtime,
            "workspace_id": workspace_id,
            "surface_id": surface_id,
            "launch_config": launch_config,
            "repo_root": repo_root,
            "project_name": project_name,
            "project_root": project_root,
            "review_bundle_path": review_bundle_path,
        },
        name=f"envctl-review-agent-{project_name}",
        daemon=False,
    )
    thread.start()


def _complete_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> None:
    workflow = _build_plan_agent_workflow(
        cli=launch_config.cli,
        preset=launch_config.preset,
        codex_cycles=launch_config.codex_cycles,
        direct_prompt_enabled=launch_config.direct_prompt_enabled,
        browser_e2e_followup_enable=launch_config.browser_e2e_followup_enable,
        pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
    )
    try:
        error = _run_surface_bootstrap(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            launch_config=launch_config,
            worktree=worktree,
        )
        if error is None:
            runtime._emit(
                "planning.agent_launch.command_sent",
                workspace_id=workspace_id,
                surface_id=surface_id,
                worktree=worktree.name,
                preset=launch_config.preset,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
            )
            return
        runtime._emit(
            "planning.agent_launch.failed",
            reason="bootstrap_failed",
            workspace_id=workspace_id,
            surface_id=surface_id,
            worktree=worktree.name,
            error=error,
        )
    finally:
        _persist_runtime_events_snapshot(runtime)


def _complete_review_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    repo_root: Path,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None,
) -> None:
    try:
        error = _run_review_surface_bootstrap(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            launch_config=launch_config,
            repo_root=repo_root,
            project_name=project_name,
            project_root=project_root,
            review_bundle_path=review_bundle_path,
        )
        if error is None:
            runtime._emit(
                "dashboard.review_tab.command_sent",
                workspace_id=workspace_id,
                surface_id=surface_id,
                project=project_name,
                cli=launch_config.cli,
                preset=_REVIEW_WORKTREE_PRESET,
            )
            return
        runtime._emit(
            "dashboard.review_tab.failed",
            reason="bootstrap_failed",
            workspace_id=workspace_id,
            surface_id=surface_id,
            project=project_name,
            cli=launch_config.cli,
            error=error,
        )
    finally:
        _persist_runtime_events_snapshot(runtime)


def _run_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> str | None:
    workflow = _build_plan_agent_workflow(
        cli=launch_config.cli,
        preset=launch_config.preset,
        codex_cycles=launch_config.codex_cycles,
        direct_prompt_enabled=launch_config.direct_prompt_enabled,
        browser_e2e_followup_enable=launch_config.browser_e2e_followup_enable,
        pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
    )
    error = _prepare_surface(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        tab_title=_tab_title_for_worktree(worktree.name),
        shell_command=_surface_respawn_command(launch_config, worktree),
    )
    if error is not None:
        return error
    send_errors = _launch_cli_bootstrap_commands(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cwd=worktree.root,
        cli_command=launch_config.cli_command,
    )
    for error in send_errors:
        if error is not None:
            return error
    _wait_for_cli_ready(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
    )
    goal_error = _maybe_submit_surface_codex_goal(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
    )
    if goal_error is not None and goal_error != "codex_goal_ready_timeout":
        return goal_error
    if goal_error is None and launch_config.codex_goal_enable and launch_config.cli == "codex":
        _wait_for_cli_ready(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            cli=launch_config.cli,
        )
    initial_step = workflow.steps[0]
    prompt_text, resolution_error = _workflow_step_prompt_text(
        runtime,
        launch_config=launch_config,
        cli=launch_config.cli,
        step=initial_step,
        worktree=worktree,
    )
    if resolution_error is not None:
        return resolution_error
    if initial_step.kind == "submit_direct_prompt":
        submit_error = _submit_direct_prompt_workflow_step(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            prompt_text=prompt_text,
        )
    else:
        submit_error = _submit_prompt_workflow_step(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            cli=launch_config.cli,
            prompt_text=prompt_text,
        )
    if submit_error is not None:
        return submit_error
    queued_steps = workflow.steps[1:]
    if queued_steps and launch_config.cli == "codex":
        queue_error_reason = _queue_codex_workflow_steps(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            worktree=worktree,
            workflow=workflow,
            queued_steps=queued_steps,
            launch_config=launch_config,
            cli=launch_config.cli,
        )
        if queue_error_reason is not None:
            failure_context = _queue_failure_event_context(queue_error_reason)
            runtime._emit(
                "planning.agent_launch.workflow_queue_failed",
                workspace_id=workspace_id,
                surface_id=surface_id,
                worktree=worktree.name,
                cli=launch_config.cli,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
                reason=queue_error_reason,
                transport="cmux",
                **failure_context,
            )
            runtime._emit(
                "planning.agent_launch.workflow_fallback",
                workspace_id=workspace_id,
                surface_id=surface_id,
                worktree=worktree.name,
                cli=launch_config.cli,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
                reason=queue_error_reason,
                transport="cmux",
                **failure_context,
            )
            return None
    return None


def _run_review_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    repo_root: Path,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None,
) -> str | None:
    error = _prepare_surface(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        tab_title=_tab_title_for_worktree(project_name),
        shell_command=launch_config.shell,
        failure_event="dashboard.review_tab.failed",
    )
    if error is not None:
        return error
    send_errors = _launch_cli_bootstrap_commands(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cwd=repo_root,
        cli_command=launch_config.cli_command,
        failure_event="dashboard.review_tab.failed",
    )
    for send_error in send_errors:
        if send_error is not None:
            return send_error
    _wait_for_cli_ready(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
    )
    review_arguments = _review_prompt_arguments(
        project_name=project_name,
        project_root=project_root,
        review_bundle_path=review_bundle_path,
        original_plan_path=_review_original_plan_path(project_name, project_root, repo_root=repo_root),
    )
    prompt_text, resolution_error = _resolve_preset_submission_text(
        runtime,
        launch_config=launch_config,
        cli=launch_config.cli,
        preset=_REVIEW_WORKTREE_PRESET,
        arguments=review_arguments,
    )
    if resolution_error is not None:
        return resolution_error
    if _uses_direct_submission(cli=launch_config.cli, direct_prompt_enabled=launch_config.direct_prompt_enabled):
        return _submit_direct_prompt_workflow_step(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            prompt_text=prompt_text,
            failure_event="dashboard.review_tab.failed",
        )
    return _submit_prompt_workflow_step(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
        prompt_text=prompt_text,
        failure_event="dashboard.review_tab.failed",
    )


def _maybe_submit_surface_codex_goal(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
) -> str | None:
    if launch_config.cli != "codex" or not launch_config.codex_goal_enable:
        return None
    goal_text = _codex_goal_text_for_worktree(
        worktree=worktree,
        preset=launch_config.preset,
        workflow_mode=workflow.mode,
        omx_workflow=launch_config.omx_workflow,
    )
    error = _submit_surface_codex_goal(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        goal_text=goal_text,
    )
    if error is None:
        _emit_codex_goal_event(
            runtime,
            "planning.agent_launch.codex_goal_submitted",
            workspace_id=workspace_id,
            surface_id=surface_id,
            cli=launch_config.cli,
            workflow=workflow,
            transport="cmux",
            worktree=worktree,
        )
        return None
    if error == "codex_goal_ready_timeout":
        _emit_codex_goal_event(
            runtime,
            "planning.agent_launch.codex_goal_fallback",
            workspace_id=workspace_id,
            surface_id=surface_id,
            cli=launch_config.cli,
            workflow=workflow,
            transport="cmux",
            worktree=worktree,
            reason=error,
        )
        return error
    return error


def _submit_surface_codex_goal(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    goal_text: str,
) -> str | None:
    submit_error = _submit_direct_prompt_workflow_step(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        prompt_text=f"/goal {goal_text}",
    )
    if submit_error is not None:
        return submit_error
    if not _wait_for_surface_codex_goal_active(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        goal_text=goal_text,
    ):
        return "codex_goal_active_timeout"
    if not _wait_for_codex_queue_ready(runtime, workspace_id=workspace_id, surface_id=surface_id):
        return "codex_goal_ready_timeout"
    return None


def _wait_for_surface_codex_goal_active(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    goal_text: str,
) -> bool:
    deadline = time.monotonic() + _CODEX_QUEUE_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        screen = _read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _codex_goal_screen_looks_active(screen, goal_text):
            return True
        time.sleep(_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS)
    return False


def _submit_prompt_workflow_step(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cli: str,
    prompt_text: str,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    failure_kwargs = {} if failure_event == "planning.agent_launch.failed" else {"failure_event": failure_event}
    final_errors = [
        _send_prompt_text(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            cli=cli,
            text=prompt_text,
            **failure_kwargs,
        ),
        _send_surface_key(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            key="ctrl+e",
            failure_event=failure_event,
        ),
    ]
    for error in final_errors:
        if error is not None:
            return error
    _wait_for_prompt_picker_ready(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=cli,
        prompt_text=prompt_text,
    )
    submit_error = _send_surface_key(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        key="enter",
        failure_event=failure_event,
    )
    if submit_error is not None:
        return submit_error
    _wait_for_prompt_submit_ready(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=cli,
        prompt_text=prompt_text,
    )
    return _send_surface_key(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        key="enter",
        failure_event=failure_event,
    )


def _submit_direct_prompt_workflow_step(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    prompt_text: str,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    paste_error = _paste_surface_text(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        text=prompt_text,
        failure_event=failure_event,
    )
    if paste_error is not None:
        return paste_error
    return _send_surface_key(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        key="enter",
        failure_event=failure_event,
    )


def _queue_codex_workflow_steps(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    worktree: CreatedPlanWorktree,
    workflow: _PlanAgentWorkflow,
    queued_steps: tuple[_PlanAgentWorkflowStep, ...],
    launch_config: PlanAgentLaunchConfig,
    cli: str,
) -> str | None:
    for step_index, step in enumerate(queued_steps):
        queued_text, resolution_error = _workflow_step_prompt_text(
            runtime,
            launch_config=launch_config,
            cli=cli,
            step=step,
            worktree=worktree,
        )
        if resolution_error is not None:
            return _QueueFailure("queue_prompt_resolution_failed", step_index=step_index, step_kind=step.kind)
        send_error = _paste_surface_text(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            text=queued_text,
            emit_failure_event=False,
        )
        if send_error is not None:
            return _QueueFailure("queue_send_failed", step_index=step_index, step_kind=step.kind)
        if not _queue_codex_message(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            text=queued_text,
            require_text_match=False,
        ):
            return _QueueFailure("queue_not_ready", step_index=step_index, step_kind=step.kind)
    runtime._emit(
        "planning.agent_launch.workflow_queued",
        workspace_id=workspace_id,
        surface_id=surface_id,
        worktree=worktree.name,
        cli=cli,
        workflow_mode=workflow.mode,
        codex_cycles=workflow.codex_cycles,
        queued_steps=len(queued_steps),
        queued_steps_confirmed=len(queued_steps),
        transport="cmux",
    )
    return None


def _wait_for_codex_queue_ready(runtime: Any, *, workspace_id: str, surface_id: str) -> bool:
    deadline = time.monotonic() + _CODEX_QUEUE_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        screen = _read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _codex_queue_screen_looks_ready(screen):
            return True
        time.sleep(_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS)
    return False


def _queue_codex_message(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    text: str,
    require_text_match: bool = True,
) -> bool:
    deadline = time.monotonic() + _CODEX_QUEUE_READY_TIMEOUT_SECONDS
    normalized_text = str(text).strip()
    picker_submitted = False
    tab_attempts = 0
    while time.monotonic() < deadline:
        screen = _read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if (
            normalized_text.startswith("/")
            and not picker_submitted
            and _prompt_picker_screen_looks_ready("codex", screen, normalized_text)
        ):
            submit_error = _send_surface_key(
                runtime,
                workspace_id=workspace_id,
                surface_id=surface_id,
                key="enter",
                emit_failure_event=False,
            )
            if submit_error is not None:
                return False
            picker_submitted = True
            time.sleep(_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS)
            continue
        if tab_attempts > 0 and _codex_queue_screen_confirms_queued(
            screen,
            text,
            require_text_match=require_text_match,
        ):
            return True
        if _codex_queue_message_needs_tab(screen, text, require_text_match=require_text_match):
            if tab_attempts >= _CODEX_QUEUE_MAX_TAB_ATTEMPTS:
                return False
            tab_error = _send_surface_key(
                runtime,
                workspace_id=workspace_id,
                surface_id=surface_id,
                key="tab",
                emit_failure_event=False,
            )
            if tab_error is not None:
                return False
            tab_attempts += 1
            time.sleep(_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS)
            continue
        time.sleep(_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS)
    return False


def _launch_cli_bootstrap_commands(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cwd: Path,
    cli_command: str,
    failure_event: str = "planning.agent_launch.failed",
) -> list[str | None]:
    typed_root = shlex.quote(str(cwd))
    return [
        _send_surface_text(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            text=f"cd {typed_root}",
            failure_event=failure_event,
        ),
        _send_surface_key(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            key="enter",
            failure_event=failure_event,
        ),
        _send_surface_text(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            text=cli_command,
            failure_event=failure_event,
        ),
        _send_surface_key(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            key="enter",
            failure_event=failure_event,
        ),
    ]


def _surface_id_from_output(raw: str) -> str | None:
    for token in raw.replace("\n", " ").split():
        normalized = token.strip()
        if normalized.startswith("surface:"):
            return normalized
    return None


def _resolve_workspace_id(
    runtime: Any,
    launch_config: PlanAgentLaunchConfig,
    *,
    workspace_mode: Literal["implementation", "current", "reviews"] = "implementation",
) -> str | None:
    if launch_config.cmux_workspace:
        return _resolve_configured_workspace_id(runtime, launch_config.cmux_workspace)
    _, target_ref = _default_workspace_target(runtime, launch_config, workspace_mode=workspace_mode)
    return target_ref


def _ensure_workspace_id(
    runtime: Any,
    launch_config: PlanAgentLaunchConfig,
    *,
    workspace_mode: Literal["implementation", "current", "reviews"] = "implementation",
    event_prefix: str = "planning.agent_launch",
) -> _WorkspaceLaunchTarget | None:
    if launch_config.cmux_workspace:
        return _ensure_configured_workspace_id(runtime, launch_config.cmux_workspace, event_prefix=event_prefix)
    target_title, resolved = _default_workspace_target(runtime, launch_config, workspace_mode=workspace_mode)
    if not target_title:
        return None
    if resolved:
        return _WorkspaceLaunchTarget(workspace_id=resolved, created=False)
    created_target, error = _create_named_workspace(runtime, title=target_title, event_prefix=event_prefix)
    if error is not None:
        runtime._emit(f"{event_prefix}.failed", reason="workspace_create_failed", workspace=target_title, error=error)
        return None
    return created_target


def _default_target_workspace_title(
    runtime: Any,
    launch_config: PlanAgentLaunchConfig,
    *,
    workspace_mode: Literal["implementation", "current", "reviews"] = "implementation",
) -> str | None:
    current_title, _ = _default_workspace_target(runtime, launch_config, workspace_mode=workspace_mode)
    return current_title


def _default_workspace_target(
    runtime: Any,
    launch_config: PlanAgentLaunchConfig,
    *,
    workspace_mode: Literal["implementation", "current", "reviews"] = "implementation",
) -> tuple[str | None, str | None]:
    if _missing_required_cmux_context(runtime, launch_config):
        return None, None
    entries = _list_workspaces(runtime)
    current_title = _current_workspace_title(
        runtime,
        require_cmux_context=launch_config.require_cmux_context,
        workspace_entries=entries,
    )
    if not current_title:
        return None, None
    if workspace_mode == "current":
        target_title = current_title
    else:
        suffix = " reviews" if workspace_mode == "reviews" else " implementation"
        target_title = current_title if current_title.endswith(suffix) else f"{current_title}{suffix}"
    for workspace_ref, workspace_title in entries:
        if workspace_title == target_title:
            return target_title, workspace_ref
    return target_title, None


def _missing_required_cmux_context(runtime: Any, launch_config: PlanAgentLaunchConfig) -> bool:
    if launch_config.cmux_workspace:
        return False
    if not launch_config.require_cmux_context:
        return False
    return not str(getattr(runtime, "env", {}).get("CMUX_WORKSPACE_ID", "")).strip()


def _current_workspace_title(
    runtime: Any,
    *,
    require_cmux_context: bool,
    workspace_entries: tuple[tuple[str, str], ...] | None = None,
) -> str | None:
    entries = workspace_entries if workspace_entries is not None else _list_workspaces(runtime)
    env_workspace = str(getattr(runtime, "env", {}).get("CMUX_WORKSPACE_ID", "")).strip()
    if env_workspace:
        for workspace_ref, workspace_title in entries:
            if workspace_ref == env_workspace:
                return workspace_title
        identified_ref = _identify_workspace_ref(runtime)
        if identified_ref:
            for workspace_ref, workspace_title in entries:
                if workspace_ref == identified_ref:
                    return workspace_title
        return None
    if not require_cmux_context:
        if entries:
            return entries[0][1]
        current_ref = _current_workspace_ref(runtime, require_cmux_context=False)
        if not current_ref:
            return None
        for workspace_ref, workspace_title in entries:
            if workspace_ref == current_ref:
                return workspace_title
    return None


def _current_workspace_ref(runtime: Any, *, require_cmux_context: bool) -> str | None:
    env_workspace = str(getattr(runtime, "env", {}).get("CMUX_WORKSPACE_ID", "")).strip()
    if env_workspace:
        return env_workspace
    if require_cmux_context:
        return None
    try:
        result = runtime.process_runner.run(
            ["cmux", "current-workspace"],
            cwd=runtime.config.base_dir,
            env=getattr(runtime, "env", {}),
            timeout=10.0,
        )
    except OSError:
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    return str(getattr(result, "stdout", "")).strip() or None


def _identify_workspace_ref(runtime: Any) -> str | None:
    try:
        result = runtime.process_runner.run(
            ["cmux", "identify"],
            cwd=runtime.config.base_dir,
            env=getattr(runtime, "env", {}),
            timeout=10.0,
        )
    except OSError:
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    return _workspace_ref_from_identify_output(str(getattr(result, "stdout", "")))


def _workspace_ref_from_identify_output(raw: str) -> str | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("caller", "focused"):
        entry = payload.get(key)
        if not isinstance(entry, dict):
            continue
        workspace_ref = str(entry.get("workspace_ref", "")).strip()
        if workspace_ref:
            return workspace_ref
    return None


def _resolve_configured_workspace_id(runtime: Any, configured: str) -> str | None:
    normalized = str(configured).strip()
    if not normalized:
        return None
    if _looks_like_workspace_handle(normalized):
        return normalized
    resolved = _resolve_workspace_ref_by_title(runtime, normalized)
    return resolved


def _ensure_configured_workspace_id(
    runtime: Any,
    configured: str,
    *,
    event_prefix: str = "planning.agent_launch",
) -> _WorkspaceLaunchTarget | None:
    normalized = str(configured).strip()
    if not normalized:
        return None
    if _looks_like_workspace_handle(normalized):
        return _WorkspaceLaunchTarget(workspace_id=normalized, created=False)
    resolved = _resolve_workspace_ref_by_title(runtime, normalized)
    if resolved:
        return _WorkspaceLaunchTarget(workspace_id=resolved, created=False)
    created_target, error = _create_named_workspace(runtime, title=normalized, event_prefix=event_prefix)
    if error is not None:
        runtime._emit(f"{event_prefix}.failed", reason="workspace_create_failed", workspace=normalized, error=error)
        return None
    return created_target


def _looks_like_workspace_handle(value: str) -> bool:
    normalized = str(value).strip()
    if not normalized:
        return False
    if normalized.startswith("workspace:"):
        return True
    if normalized.isdigit():
        return True
    return bool(
        re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            normalized,
        )
    )


def _resolve_workspace_ref_by_title(runtime: Any, title: str) -> str | None:
    for workspace_ref, workspace_title in _list_workspaces(runtime):
        if workspace_title == str(title).strip():
            return workspace_ref
    return None


def _list_workspaces(runtime: Any) -> tuple[tuple[str, str], ...]:
    try:
        result = runtime.process_runner.run(
            ["cmux", "list-workspaces"],
            cwd=runtime.config.base_dir,
            env=getattr(runtime, "env", {}),
            timeout=10.0,
        )
    except OSError:
        return ()
    if getattr(result, "returncode", 1) != 0:
        return ()
    return _workspace_entries_from_list_output(str(getattr(result, "stdout", "")))


def _workspace_entries_from_list_output(raw: str) -> tuple[tuple[str, str], ...]:
    entries: list[tuple[str, str]] = []
    pattern = re.compile(r"^\s*(?:\*\s+)?(workspace:\S+)\s+(.*?)(?:\s+\[[^\]]+\])?\s*$")
    for line in raw.splitlines():
        match = pattern.match(line)
        if match is None:
            continue
        workspace_ref = str(match.group(1) or "").strip()
        workspace_title = str(match.group(2) or "").strip()
        if workspace_ref and workspace_title:
            entries.append((workspace_ref, workspace_title))
    return tuple(entries)


def _surface_ids_from_list_output(raw: str) -> tuple[str, ...]:
    surface_ids: list[str] = []
    seen: set[str] = set()
    for token in raw.replace("\n", " ").split():
        normalized = token.strip()
        if not re.fullmatch(r"surface:\d+", normalized):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        surface_ids.append(normalized)
    return tuple(surface_ids)


def _list_workspace_surfaces(runtime: Any, *, workspace_id: str) -> tuple[str, ...] | None:
    try:
        result = runtime.process_runner.run(
            ["cmux", "list-pane-surfaces", "--workspace", workspace_id],
            cwd=runtime.config.base_dir,
            env=getattr(runtime, "env", {}),
            timeout=10.0,
        )
    except OSError:
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    return _surface_ids_from_list_output(str(getattr(result, "stdout", "")))


def _starter_surface_for_new_workspace(runtime: Any, *, workspace_id: str) -> tuple[str | None, str, int | None]:
    surface_ids = _list_workspace_surfaces(runtime, workspace_id=workspace_id)
    if surface_ids is None:
        return None, "probe_failed", None
    if len(surface_ids) == 1:
        return surface_ids[0], "single", 1
    if not surface_ids:
        return None, "none", 0
    return None, "ambiguous", len(surface_ids)


def _create_named_workspace(
    runtime: Any,
    *,
    title: str,
    event_prefix: str = "planning.agent_launch",
) -> tuple[_WorkspaceLaunchTarget | None, str | None]:
    create_result = runtime.process_runner.run(
        ["cmux", "new-workspace", "--cwd", str(runtime.config.base_dir)],
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(create_result, "returncode", 1) != 0:
        return None, _completed_process_error_text(create_result)
    workspace_ref = _workspace_ref_from_command_output(str(getattr(create_result, "stdout", "")))
    if workspace_ref is None:
        current_result = runtime.process_runner.run(
            ["cmux", "current-workspace"],
            cwd=runtime.config.base_dir,
            env=getattr(runtime, "env", {}),
            timeout=10.0,
        )
        if getattr(current_result, "returncode", 1) != 0:
            return None, _completed_process_error_text(current_result)
        workspace_ref = str(getattr(current_result, "stdout", "")).strip() or None
    if workspace_ref is None:
        return None, "workspace_create_failed"
    rename_result = runtime.process_runner.run(
        ["cmux", "rename-workspace", "--workspace", workspace_ref, title],
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(rename_result, "returncode", 1) != 0:
        return None, _completed_process_error_text(rename_result)
    runtime._emit(f"{event_prefix}.workspace_created", workspace_id=workspace_ref, title=title)
    starter_surface_id, probe_result, surface_count = _starter_surface_for_new_workspace(
        runtime,
        workspace_id=workspace_ref,
    )
    probe_payload: dict[str, object] = {
        "workspace_id": workspace_ref,
        "result": probe_result,
    }
    if surface_count is not None:
        probe_payload["surface_count"] = surface_count
    if starter_surface_id is not None:
        probe_payload["surface_id"] = starter_surface_id
    runtime._emit(f"{event_prefix}.workspace_surface_probe", **probe_payload)
    return (
        _WorkspaceLaunchTarget(
            workspace_id=workspace_ref,
            created=True,
            starter_surface_id=starter_surface_id,
            starter_surface_probe_result=probe_result,
        ),
        None,
    )


def _workspace_ref_from_command_output(raw: str) -> str | None:
    for token in raw.replace("\n", " ").split():
        normalized = token.strip()
        if normalized.startswith("workspace:"):
            return normalized
    return None


def _send_surface_text(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    text: str,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    return _run_cmux_command(
        runtime,
        ["cmux", "send", "--workspace", workspace_id, "--surface", surface_id, text],
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
    )


def _paste_surface_text(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    text: str,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    buffer_name = f"envctl-{str(surface_id).replace(':', '-')}"
    set_error = _run_cmux_command(
        runtime,
        ["cmux", "set-buffer", "--name", buffer_name, text],
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
    )
    if set_error is not None:
        return set_error
    return _run_cmux_command(
        runtime,
        ["cmux", "paste-buffer", "--name", buffer_name, "--workspace", workspace_id, "--surface", surface_id],
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
    )


def _send_prompt_text(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cli: str,
    text: str,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    _ = cli
    if failure_event == "planning.agent_launch.failed":
        return _send_surface_text(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            text=text,
        )
    return _send_surface_text(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        text=text,
        failure_event=failure_event,
    )


def _send_surface_key(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    key: str,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    return _run_cmux_command(
        runtime,
        ["cmux", "send-key", "--workspace", workspace_id, "--surface", surface_id, key],
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
    )


def _run_cmux_command(
    runtime: Any,
    command: list[str],
    *,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    result = runtime.process_runner.run(
        command,
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(result, "returncode", 1) == 0:
        return None
    error = _completed_process_error_text(result)
    if emit_failure_event:
        runtime._emit(failure_event, reason="cmux_command_failed", command=command[1], error=error)
    return error


def _completed_process_error_text(result: object) -> str:
    stderr = str(getattr(result, "stderr", "")).strip()
    stdout = str(getattr(result, "stdout", "")).strip()
    if stderr:
        return stderr
    if stdout:
        return stdout
    return f"exit:{getattr(result, 'returncode', 1)}"


def _wait_for_cli_ready(runtime: Any, *, workspace_id: str, surface_id: str, cli: str) -> None:
    normalized_cli = str(cli).strip().lower()
    timeout_seconds = _cli_ready_delay_seconds(normalized_cli)
    if normalized_cli not in {"codex", "opencode"}:
        time.sleep(timeout_seconds)
        return
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        screen = _read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _screen_looks_ready(normalized_cli, screen):
            return
        time.sleep(_CLI_READY_POLL_INTERVAL_SECONDS)


def _read_surface_screen(runtime: Any, *, workspace_id: str, surface_id: str) -> str:
    result = runtime.process_runner.run(
        [
            "cmux",
            "read-screen",
            "--workspace",
            workspace_id,
            "--surface",
            surface_id,
            "--lines",
            str(_READ_SCREEN_LINE_COUNT),
        ],
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(result, "returncode", 1) != 0:
        return ""
    return str(getattr(result, "stdout", ""))


def _wait_for_prompt_submit_ready(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cli: str,
    prompt_text: str,
) -> None:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli != "opencode":
        if normalized_cli != "codex":
            time.sleep(_PROMPT_SUBMIT_READY_DELAY_SECONDS)
            return
    deadline = time.monotonic() + _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        screen = _read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _prompt_submit_screen_looks_ready(normalized_cli, screen, prompt_text):
            return
        time.sleep(_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS)


def _wait_for_prompt_picker_ready(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cli: str,
    prompt_text: str,
) -> None:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli not in {"codex", "opencode"}:
        time.sleep(_PROMPT_PRE_SUBMIT_DELAY_SECONDS)
        return
    deadline = time.monotonic() + _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        screen = _read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _prompt_picker_screen_looks_ready(normalized_cli, screen, prompt_text):
            return
        time.sleep(_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS)


def _prepare_surface(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    tab_title: str,
    shell_command: str,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    commands = [
        ["cmux", "rename-tab", "--workspace", workspace_id, "--surface", surface_id, tab_title],
        ["cmux", "respawn-pane", "--workspace", workspace_id, "--surface", surface_id, "--command", shell_command],
    ]
    for command in commands:
        error = _run_cmux_command(runtime, command, failure_event=failure_event)
        if error is not None:
            return error
    time.sleep(_SURFACE_READY_DELAY_SECONDS)
    return None


__all__ = tuple(name for name in globals() if not name.startswith("__"))
