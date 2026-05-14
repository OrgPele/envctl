from __future__ import annotations

# ruff: noqa: F403,F405
import sys
import types
from importlib import import_module
from typing import Any

from envctl_engine.planning.plan_agent.config import *
from envctl_engine.planning.plan_agent.workflow import *
from envctl_engine.planning.plan_agent.terminal_screen import *
from envctl_engine.planning.plan_agent.recovery import *
from envctl_engine.planning.plan_agent.tmux_transport import *
from envctl_engine.planning.plan_agent.cmux_transport import *
from envctl_engine.planning.plan_agent.omx_transport import *

_PATCH_MIRROR_MODULES = (
    "envctl_engine.planning.plan_agent.config",
    "envctl_engine.planning.plan_agent.workflow",
    "envctl_engine.planning.plan_agent.terminal_screen",
    "envctl_engine.planning.plan_agent.recovery",
    "envctl_engine.planning.plan_agent.tmux_transport",
    "envctl_engine.planning.plan_agent.cmux_transport",
    "envctl_engine.planning.plan_agent.omx_transport",
)


def _export_owner_symbols() -> None:
    current_module = sys.modules[__name__]
    for module_name in _PATCH_MIRROR_MODULES:
        module = import_module(module_name)
        for name, value in vars(module).items():
            if name.startswith("__"):
                continue
            if name in {"sys", "types", "import_module", "Any"}:
                continue
            if not hasattr(current_module, name):
                setattr(current_module, name, value)


_export_owner_symbols()


class _PlanAgentLaunchModule(types.ModuleType):
    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name.startswith("__"):
            return
        for module_name in _PATCH_MIRROR_MODULES:
            module = sys.modules.get(module_name)
            if module is not None and hasattr(module, name):
                object.__setattr__(module, name, value)


sys.modules[__name__].__class__ = _PlanAgentLaunchModule


def inspect_plan_agent_launch(runtime: Any, *, route: object) -> dict[str, object]:
    launch_config = resolve_plan_agent_launch_config(runtime.config, getattr(runtime, "env", {}), route=route)
    workflow = _build_plan_agent_workflow(
        cli=launch_config.cli,
        preset=launch_config.preset,
        codex_cycles=launch_config.codex_cycles,
        direct_prompt_enabled=launch_config.direct_prompt_enabled,
        browser_e2e_followup_enable=launch_config.browser_e2e_followup_enable,
        pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
    )
    workspace_id = None if launch_config.transport == "tmux" else _resolve_workspace_id(runtime, launch_config)
    target_workspace = (
        None
        if launch_config.transport == "tmux"
        else (launch_config.cmux_workspace or _default_target_workspace_title(runtime, launch_config))
    )
    payload: dict[str, object] = {
        "enabled": launch_config.enabled,
        "transport": launch_config.transport,
        "cli": launch_config.cli,
        "preset": launch_config.preset,
        "workflow_mode": workflow.mode,
        "codex_cycles": launch_config.codex_cycles,
        "omx_workflow": launch_config.omx_workflow or None,
        "workflow_warning": launch_config.codex_cycles_warning,
        "codex_goal_enable": launch_config.codex_goal_enable,
        "shell": launch_config.shell,
        "direct_prompt_enabled": launch_config.direct_prompt_enabled,
        "ulw_loop_prefix": launch_config.ulw_loop_prefix,
        "ulw_suffix": launch_config.ulw_suffix,
        "browser_e2e_followup_enable": launch_config.browser_e2e_followup_enable,
        "pr_review_comments_followup_enable": launch_config.pr_review_comments_followup_enable,
        "require_cmux_context": launch_config.require_cmux_context,
        "workspace_id": workspace_id,
        "configured_workspace": target_workspace or None,
        "reason": "disabled",
    }
    if str(getattr(route, "command", "")).strip() != "plan":
        payload["reason"] = "not_plan_command"
        return payload
    if bool(getattr(route, "flags", {}).get("planning_prs")):
        payload["reason"] = "planning_prs_only"
        return payload
    if not launch_config.enabled:
        return payload
    if launch_config.transport == "omx" and launch_config.cli != "codex":
        payload["reason"] = "unsupported_omx_cli"
        return payload
    if _route_requests_ulw(route) and not _ulw_route_supported(launch_config=launch_config):
        payload["reason"] = "unsupported_ulw_flag"
        return payload
    if launch_config.transport == "cmux" and _missing_required_cmux_context(runtime, launch_config):
        payload["reason"] = "missing_cmux_context"
        return payload
    payload["reason"] = "awaiting_new_worktrees"
    return payload


def launch_plan_agent_terminals(
    runtime: Any,
    *,
    route: object,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
) -> PlanAgentLaunchResult:
    launch_config = resolve_plan_agent_launch_config(runtime.config, getattr(runtime, "env", {}), route=route)
    workflow = _build_plan_agent_workflow(
        cli=launch_config.cli,
        preset=launch_config.preset,
        codex_cycles=launch_config.codex_cycles,
        direct_prompt_enabled=launch_config.direct_prompt_enabled,
        browser_e2e_followup_enable=launch_config.browser_e2e_followup_enable,
        pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
    )
    base_payload = {
        "enabled": launch_config.enabled,
        "cli": launch_config.cli,
        "created_worktree_count": len(created_worktrees),
        "workflow_mode": workflow.mode,
        "codex_cycles": launch_config.codex_cycles,
        "codex_goal_enable": launch_config.codex_goal_enable,
        "browser_e2e_followup_enable": launch_config.browser_e2e_followup_enable,
        "pr_review_comments_followup_enable": launch_config.pr_review_comments_followup_enable,
    }
    if str(getattr(route, "command", "")).strip() != "plan" or bool(getattr(route, "flags", {}).get("planning_prs")):
        runtime._emit("planning.agent_launch.skipped", reason="inapplicable_route", **base_payload)
        return PlanAgentLaunchResult(status="skipped", reason="inapplicable_route")
    if not launch_config.enabled:
        runtime._emit("planning.agent_launch.skipped", reason="disabled", **base_payload)
        return PlanAgentLaunchResult(status="skipped", reason="disabled")
    if _route_requests_ulw(route) and not _ulw_route_supported(launch_config=launch_config):
        _print_launch_summary("Plan agent launch skipped: --ulw requires --tmux --opencode.")
        runtime._emit("planning.agent_launch.failed", reason="unsupported_ulw_flag", **base_payload)
        return PlanAgentLaunchResult(status="failed", reason="unsupported_ulw_flag")
    if not created_worktrees:
        _print_launch_summary("Plan agent launch skipped: no new worktrees were created.")
        runtime._emit("planning.agent_launch.skipped", reason="no_new_worktrees", **base_payload)
        return PlanAgentLaunchResult(status="skipped", reason="no_new_worktrees")
    if launch_config.transport == "cmux" and _missing_required_cmux_context(runtime, launch_config):
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
