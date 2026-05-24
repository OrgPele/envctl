from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    PlanAgentLaunchOutcome,
    _PlanAgentWorkflow,
)


SupersetInitialPromptFn = Callable[..., tuple[str, str | None]]
SupersetAgentAndPromptFn = Callable[..., tuple[str, str]]
GitBranchNameFn = Callable[..., tuple[str, str | None]]
SupersetWorkspaceNameFn = Callable[[CreatedPlanWorktree], str]
ParseSupersetJsonOutputFn = Callable[[str], Mapping[str, object] | None]
WorkspaceIdFromSupersetPayloadFn = Callable[[Mapping[str, object]], str | None]
BridgeSupersetDesktopWorkspaceFn = Callable[..., bool]
OpenSupersetWorkspaceFn = Callable[..., str | None]
VerifySupersetDesktopWorkspaceFn = Callable[..., str | None]
RestartSupersetDesktopFn = Callable[..., bool]
CompletedProcessErrorTextFn = Callable[[Any], str]
PersistRuntimeEventsSnapshotFn = Callable[[Any], None]


def launch_single_superset_worktree(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
    base_payload: dict[str, object],
    superset_initial_prompt_fn: SupersetInitialPromptFn,
    superset_agent_and_prompt_fn: SupersetAgentAndPromptFn,
    git_branch_name_fn: GitBranchNameFn,
    superset_workspace_name_fn: SupersetWorkspaceNameFn,
    parse_superset_json_output_fn: ParseSupersetJsonOutputFn,
    workspace_id_from_superset_payload_fn: WorkspaceIdFromSupersetPayloadFn,
    bridge_superset_desktop_workspace_fn: BridgeSupersetDesktopWorkspaceFn,
    open_superset_workspace_fn: OpenSupersetWorkspaceFn,
    verify_superset_desktop_workspace_fn: VerifySupersetDesktopWorkspaceFn,
    restart_superset_desktop_fn: RestartSupersetDesktopFn,
    completed_process_error_text_fn: CompletedProcessErrorTextFn,
    persist_runtime_events_snapshot_fn: PersistRuntimeEventsSnapshotFn,
) -> PlanAgentLaunchOutcome:
    prompt, prompt_error = superset_initial_prompt_fn(
        runtime,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
    )
    if prompt_error:
        runtime._emit(
            "planning.agent_launch.failed",
            reason="prompt_resolution_failed",
            transport="superset",
            worktree=worktree.name,
            error=prompt_error,
            **base_payload,
        )
        return PlanAgentLaunchOutcome(worktree.name, worktree.root, None, "failed", prompt_error)
    agent, prompt = superset_agent_and_prompt_fn(
        runtime,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
        prompt=prompt,
    )

    if launch_config.superset_workspace:
        command = [
            "superset",
            "agents",
            "run",
            "--workspace",
            launch_config.superset_workspace,
            "--agent",
            agent,
            "--prompt",
            prompt,
            "--json",
        ]
        event_name = "planning.agent_launch.superset_agent_run"
        event_payload = {
            "workspace_id": launch_config.superset_workspace,
            "project": launch_config.superset_project or None,
        }
    else:
        branch, branch_warning = git_branch_name_fn(runtime, worktree.root)
        if branch_warning:
            runtime._emit(
                "planning.agent_launch.superset_branch_fallback",
                transport="superset",
                worktree=worktree.name,
                reason=branch_warning,
                fallback=worktree.name,
            )
        command = ["superset", "workspaces", "create"]
        if launch_config.superset_host:
            command.extend(["--host", launch_config.superset_host])
        elif launch_config.superset_local:
            command.append("--local")
        command.extend(
            [
                "--project",
                launch_config.superset_project,
                "--name",
                superset_workspace_name_fn(worktree),
                "--branch",
                branch or worktree.name,
                "--agent",
                agent,
                "--prompt",
                prompt,
                "--json",
            ]
        )
        event_name = "planning.agent_launch.superset_workspace_create"
        event_payload = {
            "workspace_id": None,
            "project": launch_config.superset_project,
        }

    runtime._emit(
        event_name,
        transport="superset",
        worktree=worktree.name,
        command_kind=command[1] if len(command) > 1 else "superset",
        **event_payload,
    )
    result = runtime.process_runner.run(
        command,
        cwd=Path(worktree.root),
        env=getattr(runtime, "env", {}),
        timeout=60.0,
    )
    if getattr(result, "returncode", 1) != 0:
        error = completed_process_error_text_fn(result)
        runtime._emit(
            "planning.agent_launch.failed",
            reason="superset_command_failed",
            transport="superset",
            worktree=worktree.name,
            error=error,
            **base_payload,
        )
        return PlanAgentLaunchOutcome(worktree.name, worktree.root, None, "failed", error)

    parsed = parse_superset_json_output_fn(str(getattr(result, "stdout", "") or ""))
    if parsed is None:
        runtime._emit(
            "planning.agent_launch.superset_debug_output",
            transport="superset",
            worktree=worktree.name,
            stdout=str(getattr(result, "stdout", "") or "").strip(),
        )
        workspace_id = launch_config.superset_workspace or None
    else:
        workspace_id = workspace_id_from_superset_payload_fn(parsed) or launch_config.superset_workspace or None
        runtime._emit(
            "planning.agent_launch.superset_result",
            transport="superset",
            worktree=worktree.name,
            workspace_id=workspace_id,
            project=launch_config.superset_project or None,
        )

    bridge_applied = False
    if workspace_id and parsed is not None:
        bridge_applied = bridge_superset_desktop_workspace_fn(
            runtime,
            launch_config=launch_config,
            worktree=worktree,
            workspace_id=workspace_id,
            payload=parsed,
        )

    outcome_reason = None
    if launch_config.superset_open and workspace_id:
        open_error = open_superset_workspace_fn(
            runtime,
            launch_config=launch_config,
            worktree=worktree,
            workspace_id=workspace_id,
        )
        if open_error:
            outcome_reason = f"open_failed: {open_error}"
        else:
            desktop_error = verify_superset_desktop_workspace_fn(
                runtime,
                worktree=worktree,
                workspace_id=workspace_id,
            )
            if desktop_error and bridge_applied and restart_superset_desktop_fn(
                runtime,
                worktree=worktree,
                workspace_id=workspace_id,
            ):
                open_superset_workspace_fn(
                    runtime,
                    launch_config=launch_config,
                    worktree=worktree,
                    workspace_id=workspace_id,
                )
                desktop_error = verify_superset_desktop_workspace_fn(
                    runtime,
                    worktree=worktree,
                    workspace_id=workspace_id,
                )
            if desktop_error:
                runtime._emit(
                    "planning.agent_launch.superset_desktop_workspace_unavailable",
                    reason="superset_desktop_workspace_unavailable",
                    transport="superset",
                    worktree=worktree.name,
                    project=launch_config.superset_project or None,
                    workspace_id=workspace_id,
                    error=desktop_error,
                )
                persist_runtime_events_snapshot_fn(runtime)
                return PlanAgentLaunchOutcome(worktree.name, worktree.root, workspace_id, "failed", desktop_error)
    elif not workspace_id:
        outcome_reason = "workspace_id_unavailable"
    persist_runtime_events_snapshot_fn(runtime)
    return PlanAgentLaunchOutcome(worktree.name, worktree.root, workspace_id, "launched", outcome_reason)
