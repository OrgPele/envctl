from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentAttachTarget,
    PlanAgentAttachValidation,
    PlanAgentLaunchConfig,
    PlanAgentLaunchOutcome,
    PlanAgentLaunchResult,
    _PlanAgentWorkflow,
)


FindExistingAttachTargetFn = Callable[..., PlanAgentAttachTarget | None]
ShouldPromptExistingSessionFn = Callable[..., bool]
PromptExistingSessionActionFn = Callable[..., str]
NewSessionCommandForRouteFn = Callable[..., tuple[str, ...]]
ReadOmxSessionIdFn = Callable[[Any, CreatedPlanWorktree], str]
ReadOmxSessionIdsFn = Callable[[Any, CreatedPlanWorktree], tuple[str, ...]]
FindOmxTmuxPanesForWorktreeFn = Callable[[Any, CreatedPlanWorktree], Sequence[tuple[str, str]]]
SpawnOmxSessionForWorktreeFn = Callable[..., str | None]
WaitForOmxAttachTargetFn = Callable[..., PlanAgentAttachTarget | None]
AttachDiscoveryDiagnosticsFn = Callable[[Any, CreatedPlanWorktree], dict[str, object]]
RunTmuxExistingSessionWorkflowFn = Callable[..., str | None]
ValidatePlanAgentAttachTargetFn = Callable[..., PlanAgentAttachValidation]
MarkWorktreePlanAgentLaunchFn = Callable[..., None]
PersistRuntimeEventsSnapshotFn = Callable[[Any], None]
SummarizeFailedLaunchOutcomesFn = Callable[[list[PlanAgentLaunchOutcome]], str]
PrintLaunchSummaryFn = Callable[[str], None]
PlanAgentNativeRecoveryCommandFn = Callable[..., tuple[str, ...]]
PlanAgentRecoveryCommandTextFn = Callable[[tuple[str, ...]], str]


def launch_omx_terminals(
    runtime: Any,
    *,
    route: object,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    base_payload: Mapping[str, object],
    prompt_on_existing: bool,
    find_existing_attach_target_fn: FindExistingAttachTargetFn,
    should_prompt_existing_session_fn: ShouldPromptExistingSessionFn,
    prompt_existing_session_action_fn: PromptExistingSessionActionFn,
    new_session_command_for_route_fn: NewSessionCommandForRouteFn,
    read_omx_session_id_fn: ReadOmxSessionIdFn,
    read_omx_session_ids_fn: ReadOmxSessionIdsFn,
    find_omx_tmux_panes_for_worktree_fn: FindOmxTmuxPanesForWorktreeFn,
    spawn_omx_session_for_worktree_fn: SpawnOmxSessionForWorktreeFn,
    wait_for_omx_attach_target_fn: WaitForOmxAttachTargetFn,
    attach_discovery_diagnostics_fn: AttachDiscoveryDiagnosticsFn,
    run_tmux_existing_session_workflow_fn: RunTmuxExistingSessionWorkflowFn,
    validate_plan_agent_attach_target_fn: ValidatePlanAgentAttachTargetFn,
    mark_worktree_plan_agent_launch_fn: MarkWorktreePlanAgentLaunchFn,
    persist_runtime_events_snapshot_fn: PersistRuntimeEventsSnapshotFn,
    summarize_failed_launch_outcomes_fn: SummarizeFailedLaunchOutcomesFn,
    print_launch_summary_fn: PrintLaunchSummaryFn,
    plan_agent_native_recovery_command_fn: PlanAgentNativeRecoveryCommandFn,
    plan_agent_recovery_command_text_fn: PlanAgentRecoveryCommandTextFn,
) -> PlanAgentLaunchResult:
    if launch_config.cli != "codex":
        runtime._emit("planning.agent_launch.failed", reason="unsupported_omx_cli", **base_payload)
        return PlanAgentLaunchResult(status="failed", reason="unsupported_omx_cli")

    repo_root = Path(runtime.config.base_dir).resolve()
    attach_via = "switch-client" if str(getattr(runtime, "env", {}).get("TMUX", "")).strip() else "attach-session"
    route_flags = getattr(route, "flags", {}) or {}
    create_new_session = bool(route_flags.get("new_session"))
    existing_attach_target = find_existing_attach_target_fn(
        runtime,
        repo_root=repo_root,
        created_worktrees=created_worktrees,
    )
    if existing_attach_target is not None:
        if not create_new_session and should_prompt_existing_session_fn(
            runtime,
            prompt_on_existing=prompt_on_existing,
        ):
            action = prompt_existing_session_action_fn(
                runtime,
                attach_target=existing_attach_target,
            )
            if action == "attach":
                runtime._emit(
                    "planning.agent_launch.skipped",
                    reason="existing_omx_session_attach",
                    session_name=existing_attach_target.session_name,
                    attach_command=" ".join(existing_attach_target.attach_command),
                    **base_payload,
                )
                return PlanAgentLaunchResult(
                    status="failed",
                    reason="existing_omx_session_attach",
                    outcomes=(),
                    attach_target=existing_attach_target,
                )
            create_new_session = True
        attach_command = " ".join(existing_attach_target.attach_command)
        if not create_new_session:
            reason = f"An OMX-managed tmux session already exists for this plan. Attach with: {attach_command}"
            runtime._emit(
                "planning.agent_launch.skipped",
                reason="existing_omx_session",
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
                    new_session_command=new_session_command_for_route_fn(
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
        previous_session_id = read_omx_session_id_fn(runtime, worktree)
        previous_session_ids = read_omx_session_ids_fn(runtime, worktree)
        previous_tmux_session_names = (
            tuple(session_name for session_name, _pane_id in find_omx_tmux_panes_for_worktree_fn(runtime, worktree))
            if create_new_session
            else ()
        )
        spawn_error = spawn_omx_session_for_worktree_fn(runtime, launch_config=launch_config, worktree=worktree)
        if spawn_error is not None:
            runtime._emit(
                "planning.agent_launch.failed",
                reason="omx_spawn_failed",
                worktree=worktree.name,
                error=spawn_error,
                transport="omx",
            )
            outcomes.append(
                PlanAgentLaunchOutcome(
                    worktree_name=worktree.name,
                    worktree_root=worktree.root,
                    surface_id=None,
                    status="failed",
                    reason=spawn_error,
                )
            )
            continue
        attach_target = wait_for_omx_attach_target_fn(
            runtime,
            repo_root=repo_root,
            worktree=worktree,
            previous_session_id=previous_session_id,
            previous_session_ids=previous_session_ids,
            previous_tmux_session_names=previous_tmux_session_names,
            attach_via=attach_via,
        )
        if attach_target is None:
            diagnostics = attach_discovery_diagnostics_fn(runtime, worktree)
            runtime._emit(
                "planning.agent_launch.failed",
                reason="omx_session_unavailable",
                worktree=worktree.name,
                transport="omx",
                **diagnostics,
            )
            outcomes.append(
                PlanAgentLaunchOutcome(
                    worktree_name=worktree.name,
                    worktree_root=worktree.root,
                    surface_id=None,
                    status="failed",
                    reason="omx_session_unavailable",
                )
            )
            continue
        error = run_tmux_existing_session_workflow_fn(
            runtime,
            session_name=attach_target.session_name,
            window_name=attach_target.window_name,
            launch_config=launch_config,
            workflow=workflow,
            worktree=worktree,
        )
        if error is not None:
            runtime._emit(
                "planning.agent_launch.failed",
                reason="bootstrap_failed",
                session_name=attach_target.session_name,
                window_name=attach_target.window_name,
                worktree=worktree.name,
                error=error,
                transport="omx",
            )
            outcomes.append(
                PlanAgentLaunchOutcome(
                    worktree_name=worktree.name,
                    worktree_root=worktree.root,
                    surface_id=None,
                    status="failed",
                    reason=error,
                )
            )
            continue
        validation = validate_plan_agent_attach_target_fn(
            runtime,
            attach_target,
            worktree=worktree,
            transport="omx",
            phase="post_workflow_queue",
        )
        if not validation.ok:
            runtime._emit(
                "planning.agent_launch.failed",
                reason=validation.reason,
                session_name=attach_target.session_name,
                window_name=attach_target.window_name,
                worktree=worktree.name,
                transport="omx",
            )
            outcomes.append(
                PlanAgentLaunchOutcome(
                    worktree_name=worktree.name,
                    worktree_root=worktree.root,
                    surface_id=None,
                    status="failed",
                    reason=validation.reason,
                )
            )
            continue
        mark_worktree_plan_agent_launch_fn(
            worktree,
            status="launched",
            transport="omx",
            session_name=attach_target.session_name,
        )
        runtime._emit(
            "planning.agent_launch.surface_created",
            session_name=attach_target.session_name,
            window_name=attach_target.window_name,
            worktree=worktree.name,
            source="omx_session",
            transport="omx",
        )
        runtime._emit(
            "planning.agent_launch.command_sent",
            session_name=attach_target.session_name,
            window_name=attach_target.window_name,
            worktree=worktree.name,
            preset=launch_config.preset,
            workflow_mode=workflow.mode,
            codex_cycles=workflow.codex_cycles,
            transport="omx",
        )
        outcomes.append(
            PlanAgentLaunchOutcome(
                worktree_name=worktree.name,
                worktree_root=worktree.root,
                surface_id=None,
                status="launched",
            )
        )
        if first_attach_target is None:
            first_attach_target = attach_target

    persist_runtime_events_snapshot_fn(runtime)
    launched = [item for item in outcomes if item.status == "launched"]
    failed = [item for item in outcomes if item.status == "failed"]
    attach_target = first_attach_target or existing_attach_target
    if failed and launched:
        details = summarize_failed_launch_outcomes_fn(failed)
        suffix = f" Details: {details}." if details else ""
        print_launch_summary_fn(
            f"Plan agent launch finished with partial success: launched {len(launched)}, failed {len(failed)}.{suffix}"
        )
        recovery_command = plan_agent_recovery_command_text_fn(
            plan_agent_native_recovery_command_fn(
                runtime,
                route=route,
                launch_config=launch_config,
                created_worktrees=created_worktrees,
            )
        )
        if recovery_command:
            print_launch_summary_fn(f"recovery: {recovery_command}")
        return PlanAgentLaunchResult(
            status="partial",
            reason="partial_failure",
            outcomes=tuple(outcomes),
            attach_target=attach_target,
        )
    if failed:
        details = summarize_failed_launch_outcomes_fn(failed)
        suffix = f" Details: {details}." if details else ""
        print_launch_summary_fn(f"Plan agent launch failed for {len(failed)} worktree(s).{suffix}")
        recovery_command = plan_agent_recovery_command_text_fn(
            plan_agent_native_recovery_command_fn(
                runtime,
                route=route,
                launch_config=launch_config,
                created_worktrees=created_worktrees,
            )
        )
        if recovery_command:
            print_launch_summary_fn(f"recovery: {recovery_command}")
        return PlanAgentLaunchResult(status="failed", reason="launch_failed", outcomes=tuple(outcomes))

    print_launch_summary_fn(f"Plan agent launch prepared {len(launched)} OMX-managed tmux session(s).")
    return PlanAgentLaunchResult(
        status="launched",
        reason="launched",
        outcomes=tuple(outcomes),
        attach_target=attach_target,
    )
