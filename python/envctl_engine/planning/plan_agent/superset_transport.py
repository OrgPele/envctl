from __future__ import annotations

import json
from typing import Any

from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    PlanAgentLaunchOutcome,
    PlanAgentLaunchResult,
    _PlanAgentWorkflow,
)
from envctl_engine.planning.plan_agent.recovery import _persist_runtime_events_snapshot, _print_launch_summary
from envctl_engine.planning.plan_agent.superset_cli_support import (
    git_branch_name,
    open_superset_workspace,
    superset_workspace_name,
)
from envctl_engine.planning.plan_agent.superset_desktop_support import (
    bridge_superset_desktop_workspace,
    parse_superset_json_output,
    print_superset_outcome_details,
    restart_superset_desktop,
    superset_completed_process_error_text,
    verify_superset_desktop_workspace,
    workspace_id_from_superset_payload,
)
from envctl_engine.planning.plan_agent.superset_goal_agent_support import (
    ensure_superset_codex_goal_agent,
    superset_host_agent_db,
    write_superset_codex_goal_launcher,
)
import envctl_engine.planning.plan_agent.superset_worktree_launch_support as superset_worktree_launch_support
from envctl_engine.planning.plan_agent.workflow import (
    _codex_goal_text_for_worktree,
    _emit_codex_goal_event,
    _workflow_step_prompt_text,
)


_ensure_superset_codex_goal_agent = ensure_superset_codex_goal_agent
_git_branch_name = git_branch_name
_open_superset_workspace = open_superset_workspace
_superset_host_agent_db = superset_host_agent_db
_superset_workspace_name = superset_workspace_name
_write_superset_codex_goal_launcher = write_superset_codex_goal_launcher


def _launch_plan_agent_superset_workspaces(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    base_payload: dict[str, object],
) -> PlanAgentLaunchResult:
    if launch_config.cli != "codex":
        runtime._emit("planning.agent_launch.failed", reason="unsupported_superset_cli", **base_payload)
        return PlanAgentLaunchResult(status="failed", reason="unsupported_superset_cli")
    if not launch_config.superset_workspace and not launch_config.superset_project:
        runtime._emit("planning.agent_launch.skipped", reason="missing_superset_project", **base_payload)
        _print_launch_summary(
            "Plan agent launch skipped: Superset transport requires "
            "ENVCTL_PLAN_AGENT_SUPERSET_PROJECT or ENVCTL_PLAN_AGENT_SUPERSET_WORKSPACE."
        )
        return PlanAgentLaunchResult(status="skipped", reason="missing_superset_project")
    if launch_config.codex_cycles > 0:
        runtime._emit(
            "planning.agent_launch.superset_cycles_unsupported",
            reason="superset_public_cli_single_prompt",
            transport="superset",
            codex_cycles=launch_config.codex_cycles,
        )

    outcomes: list[PlanAgentLaunchOutcome] = []
    for worktree in created_worktrees:
        outcomes.append(
            _launch_single_superset_worktree(
                runtime,
                launch_config=launch_config,
                workflow=workflow,
                worktree=worktree,
                base_payload=base_payload,
            )
        )

    launched = [item for item in outcomes if item.status == "launched"]
    failed = [item for item in outcomes if item.status == "failed"]
    if failed and launched:
        _print_launch_summary(
            f"Superset plan agent launch finished with partial success: launched {len(launched)}, failed {len(failed)}."
        )
        print_superset_outcome_details(outcomes, launch_config=launch_config)
        return PlanAgentLaunchResult(status="partial", reason="partial_failure", outcomes=tuple(outcomes))
    if failed:
        _print_launch_summary(f"Superset plan agent launch failed for {len(failed)} worktree(s).")
        print_superset_outcome_details(outcomes, launch_config=launch_config)
        return PlanAgentLaunchResult(status="failed", reason="launch_failed", outcomes=tuple(outcomes))
    _print_launch_summary(f"Superset plan agent launch started {len(launched)} workspace/agent run(s).")
    print_superset_outcome_details(outcomes, launch_config=launch_config)
    return PlanAgentLaunchResult(status="launched", reason="launched", outcomes=tuple(outcomes))


def _launch_single_superset_worktree(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
    base_payload: dict[str, object],
) -> PlanAgentLaunchOutcome:
    return superset_worktree_launch_support.launch_single_superset_worktree(
        runtime,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
        base_payload=base_payload,
        superset_initial_prompt_fn=_superset_initial_prompt,
        superset_agent_and_prompt_fn=_superset_agent_and_prompt,
        git_branch_name_fn=_git_branch_name,
        superset_workspace_name_fn=_superset_workspace_name,
        parse_superset_json_output_fn=parse_superset_json_output,
        workspace_id_from_superset_payload_fn=workspace_id_from_superset_payload,
        bridge_superset_desktop_workspace_fn=bridge_superset_desktop_workspace,
        open_superset_workspace_fn=_open_superset_workspace,
        verify_superset_desktop_workspace_fn=verify_superset_desktop_workspace,
        restart_superset_desktop_fn=restart_superset_desktop,
        completed_process_error_text_fn=superset_completed_process_error_text,
        persist_runtime_events_snapshot_fn=_persist_runtime_events_snapshot,
    )


def _superset_initial_prompt(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
) -> tuple[str, str | None]:
    if not workflow.steps:
        return "", "prompt_resolution_failed: empty_workflow"
    step = workflow.steps[0]
    prompt, prompt_error = _workflow_step_prompt_text(
        runtime,
        launch_config=launch_config,
        cli=launch_config.cli,
        step=step,
        worktree=worktree,
    )
    if prompt_error is not None:
        return prompt, prompt_error
    return prompt, None


def _superset_agent_and_prompt(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
    prompt: str,
) -> tuple[str, str]:
    if launch_config.cli != "codex" or not launch_config.codex_goal_enable:
        return launch_config.cli, prompt
    goal_text = _codex_goal_text_for_worktree(
        worktree=worktree,
        preset=launch_config.preset,
        workflow_mode=workflow.mode,
        omx_workflow=launch_config.omx_workflow,
    )
    agent_id, error = _ensure_superset_codex_goal_agent(runtime, worktree=worktree)
    if error:
        _emit_codex_goal_event(
            runtime,
            "planning.agent_launch.codex_goal_fallback",
            cli=launch_config.cli,
            workflow=workflow,
            transport="superset",
            worktree=worktree,
            reason=error,
        )
        return launch_config.cli, prompt
    _emit_codex_goal_event(
        runtime,
        "planning.agent_launch.codex_goal_launcher_prepared",
        cli=launch_config.cli,
        workflow=workflow,
        transport="superset",
        worktree=worktree,
    )
    return agent_id, json.dumps({"version": 1, "goal": goal_text, "prompt": prompt}, separators=(",", ":"))


__all__ = tuple(name for name in globals() if not name.startswith("__"))
