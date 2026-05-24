from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentAttachTarget,
    PlanAgentLaunchConfig,
    PlanAgentLaunchOutcome,
    PlanAgentLaunchResult,
    _PlanAgentWorkflow,
)


ShouldPromptExistingSessionFn = Callable[..., bool]
PromptExistingSessionActionFn = Callable[..., str]
FindExistingAttachTargetFn = Callable[..., PlanAgentAttachTarget | None]
NewSessionCommandForRouteFn = Callable[..., tuple[str, ...]]
TmuxSessionNameForWorktreeFn = Callable[..., str]
NextAvailableTmuxSessionNameFn = Callable[[Any, str], str]
TmuxWindowNameForWorktreeFn = Callable[[CreatedPlanWorktree], str]
LaunchSingleTmuxWorktreeFn = Callable[..., PlanAgentLaunchOutcome]
GuidanceAttachCommandFn = Callable[[str], tuple[str, ...]]
SummarizeFailedLaunchOutcomesFn = Callable[[list[PlanAgentLaunchOutcome]], str]
PrintLaunchSummaryFn = Callable[[str], None]


def launch_tmux_terminals(
    runtime: Any,
    *,
    route: object,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    base_payload: Mapping[str, object],
    prompt_on_existing: bool,
    should_prompt_existing_session_fn: ShouldPromptExistingSessionFn,
    prompt_existing_session_action_fn: PromptExistingSessionActionFn,
    find_existing_attach_target_fn: FindExistingAttachTargetFn,
    new_session_command_for_route_fn: NewSessionCommandForRouteFn,
    tmux_session_name_for_worktree_fn: TmuxSessionNameForWorktreeFn,
    next_available_tmux_session_name_fn: NextAvailableTmuxSessionNameFn,
    tmux_window_name_for_worktree_fn: TmuxWindowNameForWorktreeFn,
    launch_single_tmux_worktree_fn: LaunchSingleTmuxWorktreeFn,
    guidance_attach_command_fn: GuidanceAttachCommandFn,
    summarize_failed_launch_outcomes_fn: SummarizeFailedLaunchOutcomesFn,
    print_launch_summary_fn: PrintLaunchSummaryFn,
) -> PlanAgentLaunchResult:
    repo_root = Path(runtime.config.base_dir).resolve()
    attach_via = "switch-client" if str(getattr(runtime, "env", {}).get("TMUX", "")).strip() else "attach-session"
    route_flags = getattr(route, "flags", {}) or {}
    create_new_session = bool(route_flags.get("new_session"))
    prompt_existing_possible = not create_new_session and should_prompt_existing_session_fn(
        runtime,
        prompt_on_existing=prompt_on_existing,
    )
    existing_attach_target = find_existing_attach_target_fn(
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
            action = prompt_existing_session_action_fn(runtime, attach_target=existing_attach_target)
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
        session_name = tmux_session_name_for_worktree_fn(repo_root, worktree, cli=launch_config.cli)
        if create_new_session:
            session_name = next_available_tmux_session_name_fn(runtime, session_name)
        window_name = tmux_window_name_for_worktree_fn(worktree)
        outcome = launch_single_tmux_worktree_fn(
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
                attach_command=guidance_attach_command_fn(session_name),
            )

    launched = [item for item in outcomes if item.status == "launched"]
    failed = [item for item in outcomes if item.status == "failed"]
    attach_target = first_attach_target or existing_attach_target
    if failed and launched:
        details = summarize_failed_launch_outcomes_fn(failed)
        suffix = f" Details: {details}." if details else ""
        print_launch_summary_fn(
            f"Plan agent launch finished with partial success: launched {len(launched)}, failed {len(failed)}.{suffix}"
        )
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
        return PlanAgentLaunchResult(status="failed", reason="launch_failed", outcomes=tuple(outcomes))
    print_launch_summary_fn(f"Plan agent launch prepared {len(launched)} tmux session(s).")
    return PlanAgentLaunchResult(
        status="launched",
        reason="launched",
        outcomes=tuple(outcomes),
        attach_target=attach_target,
    )
