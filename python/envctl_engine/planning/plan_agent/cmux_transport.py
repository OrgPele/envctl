from __future__ import annotations

# ruff: noqa: F401,F403,F405
import os
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

import envctl_engine.planning.plan_agent.cmux_workspace_support as cmux_workspace_support
import envctl_engine.planning.plan_agent.cmux_surface_support as cmux_surface_support
import envctl_engine.planning.plan_agent.cmux_workflow_submission_support as cmux_workflow_submission_support
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
    if goal_error is not None:
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
    return cmux_workflow_submission_support.submit_prompt_workflow_step(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=cli,
        prompt_text=prompt_text,
        failure_event=failure_event,
        send_prompt_text_fn=_send_prompt_text,
        send_surface_key_fn=_send_surface_key,
        wait_for_prompt_picker_ready_fn=_wait_for_prompt_picker_ready,
        wait_for_prompt_submit_ready_fn=_wait_for_prompt_submit_ready,
    )


def _submit_direct_prompt_workflow_step(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    prompt_text: str,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    return cmux_workflow_submission_support.submit_direct_prompt_workflow_step(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        prompt_text=prompt_text,
        failure_event=failure_event,
        paste_surface_text_fn=_paste_surface_text,
        send_surface_key_fn=_send_surface_key,
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
    return cmux_workflow_submission_support.queue_codex_workflow_steps(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        worktree=worktree,
        workflow=workflow,
        queued_steps=queued_steps,
        launch_config=launch_config,
        cli=cli,
        workflow_step_prompt_text_fn=_workflow_step_prompt_text,
        codex_goal_text_for_worktree_fn=_codex_goal_text_for_worktree,
        paste_surface_text_fn=_paste_surface_text,
        queue_codex_message_fn=_queue_codex_message,
    )


def _wait_for_codex_queue_ready(runtime: Any, *, workspace_id: str, surface_id: str) -> bool:
    return cmux_workflow_submission_support.wait_for_codex_queue_ready(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        read_surface_screen_fn=_read_surface_screen,
    )


def _queue_codex_message(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    text: str,
    require_text_match: bool = True,
) -> bool:
    return cmux_workflow_submission_support.queue_codex_message(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        text=text,
        require_text_match=require_text_match,
        read_surface_screen_fn=_read_surface_screen,
        send_surface_key_fn=_send_surface_key,
    )


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
    return cmux_workspace_support.surface_id_from_output(raw)


def _resolve_workspace_id(
    runtime: Any,
    launch_config: PlanAgentLaunchConfig,
    *,
    workspace_mode: Literal["implementation", "current", "reviews"] = "implementation",
) -> str | None:
    if launch_config.cmux_workspace:
        return _resolve_configured_workspace_id(runtime, launch_config.cmux_workspace)
    return cmux_workspace_support.resolve_workspace_id(runtime, launch_config, workspace_mode=workspace_mode)


def _ensure_workspace_id(
    runtime: Any,
    launch_config: PlanAgentLaunchConfig,
    *,
    workspace_mode: Literal["implementation", "current", "reviews"] = "implementation",
    event_prefix: str = "planning.agent_launch",
) -> _WorkspaceLaunchTarget | None:
    if launch_config.cmux_workspace:
        return _ensure_configured_workspace_id(runtime, launch_config.cmux_workspace, event_prefix=event_prefix)
    return cmux_workspace_support.ensure_workspace_id(
        runtime,
        launch_config,
        workspace_mode=workspace_mode,
        event_prefix=event_prefix,
    )


def _default_target_workspace_title(
    runtime: Any,
    launch_config: PlanAgentLaunchConfig,
    *,
    workspace_mode: Literal["implementation", "current", "reviews"] = "implementation",
) -> str | None:
    return cmux_workspace_support.default_target_workspace_title(
        runtime,
        launch_config,
        workspace_mode=workspace_mode,
    )


def _default_workspace_target(
    runtime: Any,
    launch_config: PlanAgentLaunchConfig,
    *,
    workspace_mode: Literal["implementation", "current", "reviews"] = "implementation",
) -> tuple[str | None, str | None]:
    return cmux_workspace_support.default_workspace_target(runtime, launch_config, workspace_mode=workspace_mode)


def _missing_required_cmux_context(runtime: Any, launch_config: PlanAgentLaunchConfig) -> bool:
    return cmux_workspace_support.missing_required_cmux_context(runtime, launch_config)


def _current_workspace_title(
    runtime: Any,
    *,
    require_cmux_context: bool,
    workspace_entries: tuple[tuple[str, str], ...] | None = None,
) -> str | None:
    return cmux_workspace_support.current_workspace_title(
        runtime,
        require_cmux_context=require_cmux_context,
        workspace_entries=workspace_entries,
    )


def _current_workspace_ref(runtime: Any, *, require_cmux_context: bool) -> str | None:
    return cmux_workspace_support.current_workspace_ref(runtime, require_cmux_context=require_cmux_context)


def _identify_workspace_ref(runtime: Any) -> str | None:
    return cmux_workspace_support.identify_workspace_ref(runtime)


def _workspace_ref_from_identify_output(raw: str) -> str | None:
    return cmux_workspace_support.workspace_ref_from_identify_output(raw)


def _resolve_configured_workspace_id(runtime: Any, configured: str) -> str | None:
    return cmux_workspace_support.resolve_configured_workspace_id(runtime, configured)


def _ensure_configured_workspace_id(
    runtime: Any,
    configured: str,
    *,
    event_prefix: str = "planning.agent_launch",
) -> _WorkspaceLaunchTarget | None:
    return cmux_workspace_support.ensure_configured_workspace_id(
        runtime,
        configured,
        event_prefix=event_prefix,
    )


def _looks_like_workspace_handle(value: str) -> bool:
    return cmux_workspace_support.looks_like_workspace_handle(value)


def _resolve_workspace_ref_by_title(runtime: Any, title: str) -> str | None:
    return cmux_workspace_support.resolve_workspace_ref_by_title(runtime, title)


def _list_workspaces(runtime: Any) -> tuple[tuple[str, str], ...]:
    return cmux_workspace_support.list_workspaces(runtime)


def _workspace_entries_from_list_output(raw: str) -> tuple[tuple[str, str], ...]:
    return cmux_workspace_support.workspace_entries_from_list_output(raw)


def _surface_ids_from_list_output(raw: str) -> tuple[str, ...]:
    return cmux_workspace_support.surface_ids_from_list_output(raw)


def _list_workspace_surfaces(runtime: Any, *, workspace_id: str) -> tuple[str, ...] | None:
    return cmux_workspace_support.list_workspace_surfaces(runtime, workspace_id=workspace_id)


def _starter_surface_for_new_workspace(runtime: Any, *, workspace_id: str) -> tuple[str | None, str, int | None]:
    return cmux_workspace_support.starter_surface_for_new_workspace(runtime, workspace_id=workspace_id)


def _create_named_workspace(
    runtime: Any,
    *,
    title: str,
    event_prefix: str = "planning.agent_launch",
) -> tuple[_WorkspaceLaunchTarget | None, str | None]:
    return cmux_workspace_support.create_named_workspace(runtime, title=title, event_prefix=event_prefix)


def _workspace_ref_from_command_output(raw: str) -> str | None:
    return cmux_workspace_support.workspace_ref_from_command_output(raw)


def _send_surface_text(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    text: str,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    return cmux_surface_support.send_surface_text(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        text=text,
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
    return cmux_surface_support.paste_surface_text(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        text=text,
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
    return cmux_surface_support.send_prompt_text(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=cli,
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
    return cmux_surface_support.send_surface_key(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        key=key,
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
    return cmux_surface_support.run_cmux_command(
        runtime,
        command,
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
    )


def _completed_process_error_text(result: object) -> str:
    return cmux_surface_support.completed_process_error_text(result)


def _wait_for_cli_ready(runtime: Any, *, workspace_id: str, surface_id: str, cli: str) -> None:
    cmux_surface_support.wait_for_cli_ready(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=cli,
        cli_ready_delay_seconds=_cli_ready_delay_seconds(str(cli).strip().lower()),
    )


def _read_surface_screen(runtime: Any, *, workspace_id: str, surface_id: str) -> str:
    return cmux_surface_support.read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)


def _wait_for_prompt_submit_ready(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cli: str,
    prompt_text: str,
) -> None:
    cmux_surface_support.wait_for_prompt_submit_ready(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=cli,
        prompt_text=prompt_text,
    )


def _wait_for_prompt_picker_ready(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cli: str,
    prompt_text: str,
) -> None:
    cmux_surface_support.wait_for_prompt_picker_ready(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=cli,
        prompt_text=prompt_text,
    )


def _prepare_surface(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    tab_title: str,
    shell_command: str,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    return cmux_surface_support.prepare_surface(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        tab_title=tab_title,
        shell_command=shell_command,
        failure_event=failure_event,
    )


__all__ = tuple(name for name in globals() if not name.startswith("__"))
