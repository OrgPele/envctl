from __future__ import annotations

# ruff: noqa: F403,F405
import json
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.constants import *
from envctl_engine.planning.plan_agent.models import *
from envctl_engine.planning.plan_agent.recovery import _persist_runtime_events_snapshot, _print_launch_summary
from envctl_engine.planning.plan_agent.workflow import _tab_title_for_worktree, _workflow_step_prompt_text


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
        _print_superset_outcome_details(outcomes, launch_config=launch_config)
        return PlanAgentLaunchResult(status="partial", reason="partial_failure", outcomes=tuple(outcomes))
    if failed:
        _print_launch_summary(f"Superset plan agent launch failed for {len(failed)} worktree(s).")
        _print_superset_outcome_details(outcomes, launch_config=launch_config)
        return PlanAgentLaunchResult(status="failed", reason="launch_failed", outcomes=tuple(outcomes))
    _print_launch_summary(f"Superset plan agent launch started {len(launched)} workspace/agent run(s).")
    _print_superset_outcome_details(outcomes, launch_config=launch_config)
    return PlanAgentLaunchResult(status="launched", reason="launched", outcomes=tuple(outcomes))


def _launch_single_superset_worktree(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
    base_payload: dict[str, object],
) -> PlanAgentLaunchOutcome:
    prompt, prompt_error = _superset_initial_prompt(
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

    if launch_config.superset_workspace:
        command = [
            "superset",
            "agents",
            "run",
            "--workspace",
            launch_config.superset_workspace,
            "--agent",
            launch_config.cli,
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
        branch, branch_warning = _git_branch_name(runtime, worktree.root)
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
        # Superset's public CLI accepts project and branch, but not an explicit worktree path.
        command.extend(
            [
                "--project",
                launch_config.superset_project,
                "--name",
                _superset_workspace_name(worktree),
                "--branch",
                branch or worktree.name,
                "--agent",
                launch_config.cli,
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
        error = _completed_process_error_text(result)
        runtime._emit(
            "planning.agent_launch.failed",
            reason="superset_command_failed",
            transport="superset",
            worktree=worktree.name,
            error=error,
            **base_payload,
        )
        return PlanAgentLaunchOutcome(worktree.name, worktree.root, None, "failed", error)

    parsed = _parse_superset_json_output(str(getattr(result, "stdout", "") or ""))
    if parsed is None:
        runtime._emit(
            "planning.agent_launch.superset_debug_output",
            transport="superset",
            worktree=worktree.name,
            stdout=str(getattr(result, "stdout", "") or "").strip(),
        )
        workspace_id = launch_config.superset_workspace or None
    else:
        workspace_id = _workspace_id_from_superset_payload(parsed) or launch_config.superset_workspace or None
        runtime._emit(
            "planning.agent_launch.superset_result",
            transport="superset",
            worktree=worktree.name,
            workspace_id=workspace_id,
            project=launch_config.superset_project or None,
        )

    outcome_reason = None
    if launch_config.superset_open and workspace_id:
        open_error = _open_superset_workspace(
            runtime,
            launch_config=launch_config,
            worktree=worktree,
            workspace_id=workspace_id,
        )
        if open_error:
            outcome_reason = f"open_failed: {open_error}"
    elif not workspace_id:
        outcome_reason = "workspace_id_unavailable"
    _persist_runtime_events_snapshot(runtime)
    return PlanAgentLaunchOutcome(worktree.name, worktree.root, workspace_id, "launched", outcome_reason)


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
    return _workflow_step_prompt_text(
        runtime,
        launch_config=launch_config,
        cli=launch_config.cli,
        step=step,
        worktree=worktree,
    )


def _git_branch_name(runtime: Any, cwd: Path) -> tuple[str, str | None]:
    result = runtime.process_runner.run(
        ["git", "-C", str(cwd), "branch", "--show-current"],
        cwd=cwd,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(result, "returncode", 1) != 0:
        return "", "git_branch_unavailable"
    branch = str(getattr(result, "stdout", "") or "").strip()
    if not branch:
        return "", "git_branch_unavailable"
    return branch, None


def _superset_workspace_name(worktree: CreatedPlanWorktree) -> str:
    return _tab_title_for_worktree(worktree.name)


def _open_superset_workspace(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
    workspace_id: str,
) -> str | None:
    command = ["superset", "workspaces", "open", workspace_id]
    runtime._emit(
        "planning.agent_launch.superset_open",
        transport="superset",
        worktree=worktree.name,
        project=launch_config.superset_project or None,
        workspace_id=workspace_id,
        command_kind="open",
    )
    result = runtime.process_runner.run(
        command,
        cwd=Path(worktree.root),
        env=getattr(runtime, "env", {}),
        timeout=30.0,
    )
    if getattr(result, "returncode", 1) == 0:
        return None
    error = _completed_process_error_text(result)
    runtime._emit(
        "planning.agent_launch.superset_open_failed",
        reason="superset_open_failed",
        transport="superset",
        worktree=worktree.name,
        project=launch_config.superset_project or None,
        workspace_id=workspace_id,
        error=error,
    )
    return error


def _print_superset_outcome_details(
    outcomes: list[PlanAgentLaunchOutcome],
    *,
    launch_config: PlanAgentLaunchConfig,
) -> None:
    for outcome in outcomes:
        if outcome.status == "failed":
            suffix = f": {outcome.reason}" if outcome.reason else ""
            _print_launch_summary(f"  - {outcome.worktree_name}: failed{suffix}")
            continue
        workspace_id = str(outcome.surface_id or "").strip()
        if workspace_id:
            _print_launch_summary(f"  - {outcome.worktree_name}: launched Superset workspace {workspace_id}")
            if not launch_config.superset_open:
                _print_launch_summary(f"    open: superset workspaces open {workspace_id}")
        else:
            _print_launch_summary(
                f"  - {outcome.worktree_name}: Superset command succeeded, but no workspace id was returned."
            )
        reason = str(outcome.reason or "").strip()
        if reason.startswith("open_failed:"):
            _print_launch_summary(f"    open failed: {reason.removeprefix('open_failed:').strip()}")


def _parse_superset_json_output(stdout: str) -> dict[str, Any] | list[Any] | None:
    text = str(stdout or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, (dict, list)):
        return parsed
    return None


def _workspace_id_from_superset_payload(payload: dict[str, Any] | list[Any]) -> str | None:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                found = _workspace_id_from_superset_payload(item)
                if found:
                    return found
        return None
    workspace = payload.get("workspace")
    if isinstance(workspace, dict):
        workspace_id = str(workspace.get("id") or "").strip()
        if workspace_id:
            return workspace_id
    workspace_id = str(payload.get("workspace_id") or payload.get("id") or "").strip()
    if workspace_id:
        return workspace_id
    agents = payload.get("agents")
    if isinstance(agents, list):
        for item in agents:
            if isinstance(item, dict):
                workspace_id = str(item.get("workspace_id") or "").strip()
                if workspace_id:
                    return workspace_id
    return None


def _completed_process_error_text(result: object) -> str:
    stderr = str(getattr(result, "stderr", "") or "").strip()
    stdout = str(getattr(result, "stdout", "") or "").strip()
    if stderr and stdout:
        return f"{stderr}\n{stdout}"
    if stderr:
        return stderr
    if stdout:
        return stdout
    return f"exit:{getattr(result, 'returncode', 1)}"


__all__ = tuple(name for name in globals() if not name.startswith("__"))
