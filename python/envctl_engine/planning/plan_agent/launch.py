from __future__ import annotations

from typing import Any

from envctl_engine.planning.plan_agent.cmux_transport import (
    _default_target_workspace_title,
    _ensure_workspace_id,
    _launch_single_worktree,
)
from envctl_engine.planning.plan_agent.config import (
    _missing_launch_commands,
)
from envctl_engine.planning.plan_agent.constants import _PLAN_AGENT_WORKFLOW_CODEX_CYCLES
from envctl_engine.planning.plan_agent.launch_evaluation import build_plan_agent_launch_evaluation
from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchOutcome,
    PlanAgentLaunchResult,
)
from envctl_engine.planning.plan_agent.omx_transport import _launch_plan_agent_omx_terminals
from envctl_engine.planning.plan_agent.recovery import _print_launch_summary
from envctl_engine.planning.plan_agent.superset_transport import _launch_plan_agent_superset_workspaces
from envctl_engine.planning.plan_agent.tmux_transport import (
    _launch_plan_agent_tmux_terminals,
    _run_tmux_existing_session_workflow,
)


def inspect_plan_agent_launch(runtime: Any, *, route: object) -> dict[str, object]:
    return build_plan_agent_launch_evaluation(runtime, route=route).inspection_payload()


def launch_plan_agent_terminals(
    runtime: Any,
    *,
    route: object,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
) -> PlanAgentLaunchResult:
    evaluation = build_plan_agent_launch_evaluation(runtime, route=route, include_workspace_details=False)
    launch_config = evaluation.launch_config
    workflow = evaluation.workflow
    base_payload = evaluation.base_payload(created_worktree_count=len(created_worktrees))
    if evaluation.route_inapplicable:
        runtime._emit("planning.agent_launch.skipped", reason="inapplicable_route", **base_payload)
        return PlanAgentLaunchResult(status="skipped", reason="inapplicable_route")
    if evaluation.inspection_reason == "disabled":
        runtime._emit("planning.agent_launch.skipped", reason="disabled", **base_payload)
        return PlanAgentLaunchResult(status="skipped", reason="disabled")
    if launch_config.surface_transport_warning:
        _print_launch_summary(
            "Plan agent launch failed: ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT must be 'cmux', 'tmux', or 'superset'."
        )
        runtime._emit("planning.agent_launch.failed", reason=launch_config.surface_transport_warning, **base_payload)
        return PlanAgentLaunchResult(status="failed", reason=launch_config.surface_transport_warning)
    if evaluation.inspection_reason == "unsupported_ulw_flag":
        _print_launch_summary("Plan agent launch skipped: --ulw requires --opencode.")
        runtime._emit("planning.agent_launch.failed", reason="unsupported_ulw_flag", **base_payload)
        return PlanAgentLaunchResult(status="failed", reason="unsupported_ulw_flag")
    if not created_worktrees:
        _print_launch_summary("Plan agent launch skipped: no new worktrees were created.")
        runtime._emit("planning.agent_launch.skipped", reason="no_new_worktrees", **base_payload)
        return PlanAgentLaunchResult(status="skipped", reason="no_new_worktrees")
    if evaluation.inspection_reason == "missing_cmux_context":
        _print_launch_summary(
            "Plan agent launch skipped: no active cmux workspace context found. "
            "Fix by setting ENVCTL_PLAN_AGENT_CMUX_WORKSPACE=<workspace-id>, "
            "setting ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT=false, "
            "or running envctl from within an active cmux session."
        )
        runtime._emit("planning.agent_launch.skipped", reason="missing_cmux_context", **base_payload)
        return PlanAgentLaunchResult(status="skipped", reason="missing_cmux_context")
    missing_commands = _missing_launch_commands(runtime, launch_config)
    if missing_commands:
        message = f"Plan agent launch skipped: missing required executables: {', '.join(missing_commands)}."
        _print_launch_summary(message)
        runtime._emit(
            "planning.agent_launch.failed",
            reason="missing_executables",
            missing=missing_commands,
            **base_payload,
        )
        return PlanAgentLaunchResult(status="failed", reason="missing_executables")
    if launch_config.transport == "omx":
        return _launch_plan_agent_omx_terminals(
            runtime,
            route=route,
            launch_config=launch_config,
            workflow=workflow,
            created_worktrees=created_worktrees,
            base_payload=base_payload,
            prompt_on_existing=not bool(getattr(route, "flags", {}).get("batch")),
            run_tmux_existing_session_workflow=_run_tmux_existing_session_workflow,
        )
    if launch_config.transport == "tmux":
        return _launch_plan_agent_tmux_terminals(
            runtime,
            route=route,
            launch_config=launch_config,
            workflow=workflow,
            created_worktrees=created_worktrees,
            base_payload=base_payload,
            prompt_on_existing=not bool(getattr(route, "flags", {}).get("batch")),
        )
    if launch_config.transport == "superset":
        return _launch_plan_agent_superset_workspaces(
            runtime,
            launch_config=launch_config,
            workflow=workflow,
            created_worktrees=created_worktrees,
            base_payload=base_payload,
        )

    workspace_target = _ensure_workspace_id(runtime, launch_config)
    target_workspace = launch_config.cmux_workspace
    if workspace_target is None and not target_workspace:
        target_workspace = _default_target_workspace_title(runtime, launch_config)
    if workspace_target is None and target_workspace:
        _print_launch_summary("Plan agent launch failed: unable to resolve or create the configured cmux workspace.")
        return PlanAgentLaunchResult(status="failed", reason="workspace_unavailable")
    if workspace_target is None:
        _print_launch_summary("Plan agent launch skipped: current cmux workspace context is unavailable.")
        runtime._emit("planning.agent_launch.skipped", reason="missing_cmux_context", **base_payload)
        return PlanAgentLaunchResult(status="skipped", reason="missing_cmux_context")

    workspace_id = workspace_target.workspace_id
    runtime._emit(
        "planning.agent_launch.evaluate",
        reason="ready",
        workspace_id=workspace_id,
        preset=launch_config.preset,
        **base_payload,
    )
    runtime._emit(
        "planning.agent_launch.workflow_selected",
        workspace_id=workspace_id,
        warning=launch_config.codex_cycles_warning,
        **base_payload,
    )
    if workflow.mode == _PLAN_AGENT_WORKFLOW_CODEX_CYCLES:
        _print_launch_summary(
            "Plan agent launch queued Codex cycle workflow "
            f"(cycles={workflow.codex_cycles}) for {len(created_worktrees)} surface(s)."
        )
    if (
        workspace_target.created
        and workspace_target.starter_surface_id is None
        and workspace_target.starter_surface_probe_result in {"none", "ambiguous", "probe_failed"}
    ):
        runtime._emit(
            "planning.agent_launch.surface_fallback",
            workspace_id=workspace_id,
            reason=workspace_target.starter_surface_probe_result,
        )
    outcomes: list[PlanAgentLaunchOutcome] = []
    starter_surface_id = workspace_target.starter_surface_id
    for worktree in created_worktrees:
        outcome = _launch_single_worktree(
            runtime,
            workspace_id=workspace_id,
            launch_config=launch_config,
            worktree=worktree,
            starter_surface_id=starter_surface_id,
        )
        outcomes.append(outcome)
        starter_surface_id = None

    launched = [item for item in outcomes if item.status == "launched"]
    failed = [item for item in outcomes if item.status == "failed"]
    if failed and launched:
        _print_launch_summary(
            f"Plan agent launch finished with partial success: launched {len(launched)}, failed {len(failed)}."
        )
        return PlanAgentLaunchResult(status="partial", reason="partial_failure", outcomes=tuple(outcomes))
    if failed:
        _print_launch_summary(f"Plan agent launch failed for {len(failed)} worktree(s).")
        return PlanAgentLaunchResult(status="failed", reason="launch_failed", outcomes=tuple(outcomes))
    _print_launch_summary(f"Plan agent launch opened {len(launched)} cmux surface(s).")
    return PlanAgentLaunchResult(status="launched", reason="launched", outcomes=tuple(outcomes))
