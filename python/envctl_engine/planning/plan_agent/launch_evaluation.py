from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from envctl_engine.planning.plan_agent.cmux_workspace_support import (
    default_target_workspace_title,
    missing_required_cmux_context,
    resolve_workspace_id,
)
from envctl_engine.planning.plan_agent.config import (
    _codex_tui_queue_workflow_supported,
    _route_requests_ulw,
    _ulw_route_supported,
    resolve_plan_agent_launch_config,
)
from envctl_engine.planning.plan_agent.models import PlanAgentLaunchConfig, _PlanAgentWorkflow
from envctl_engine.planning.plan_agent.workflow_build import _build_plan_agent_workflow


@dataclass(frozen=True, slots=True)
class PlanAgentLaunchEvaluation:
    launch_config: PlanAgentLaunchConfig
    workflow: _PlanAgentWorkflow
    route_is_plan: bool
    planning_prs_only: bool
    workspace_id: str | None
    configured_workspace: str | None
    inspection_reason: str

    @property
    def route_inapplicable(self) -> bool:
        return not self.route_is_plan or self.planning_prs_only

    def base_payload(self, *, created_worktree_count: int) -> dict[str, object]:
        return {
            "enabled": self.launch_config.enabled,
            "cli": self.launch_config.cli,
            "created_worktree_count": created_worktree_count,
            "workflow_mode": self.workflow.mode,
            "codex_cycles": self.launch_config.codex_cycles,
            "codex_goal_enable": self.launch_config.codex_goal_enable,
            "browser_e2e_followup_enable": self.launch_config.browser_e2e_followup_enable,
            "fullstack_pr_url_e2e_enable": self.launch_config.fullstack_pr_url_e2e_enable,
            "fullstack_pr_url_e2e_active": self.launch_config.fullstack_pr_url_e2e_active,
            "fullstack_pr_url_e2e_reason": self.launch_config.fullstack_pr_url_e2e_reason,
            "pr_review_comments_followup_enable": self.launch_config.pr_review_comments_followup_enable,
        }

    def inspection_payload(self) -> dict[str, object]:
        return {
            "enabled": self.launch_config.enabled,
            "transport": self.launch_config.transport,
            "cli": self.launch_config.cli,
            "preset": self.launch_config.preset,
            "workflow_mode": self.workflow.mode,
            "codex_cycles": self.launch_config.codex_cycles,
            "omx_workflow": self.launch_config.omx_workflow or None,
            "workflow_warning": self.launch_config.codex_cycles_warning,
            "codex_goal_enable": self.launch_config.codex_goal_enable,
            "shell": self.launch_config.shell,
            "direct_prompt_enabled": self.launch_config.direct_prompt_enabled,
            "ulw_loop_prefix": self.launch_config.ulw_loop_prefix,
            "ulw_suffix": self.launch_config.ulw_suffix,
            "browser_e2e_followup_enable": self.launch_config.browser_e2e_followup_enable,
            "fullstack_pr_url_e2e_enable": self.launch_config.fullstack_pr_url_e2e_enable,
            "fullstack_pr_url_e2e_active": self.launch_config.fullstack_pr_url_e2e_active,
            "fullstack_pr_url_e2e_reason": self.launch_config.fullstack_pr_url_e2e_reason,
            "pr_review_comments_followup_enable": self.launch_config.pr_review_comments_followup_enable,
            "require_cmux_context": self.launch_config.require_cmux_context,
            "workspace_id": self.workspace_id,
            "configured_workspace": self.configured_workspace,
            "superset_project": self.launch_config.superset_project or None,
            "superset_host": self.launch_config.superset_host or None,
            "superset_local": self.launch_config.superset_local,
            "superset_open": self.launch_config.superset_open,
            "reason": self.inspection_reason,
        }


def build_plan_agent_launch_evaluation(
    runtime: Any,
    *,
    route: object,
    include_workspace_details: bool = True,
) -> PlanAgentLaunchEvaluation:
    launch_config = resolve_plan_agent_launch_config(runtime.config, getattr(runtime, "env", {}), route=route)
    workflow = _build_plan_agent_workflow(
        cli=launch_config.cli,
        preset=launch_config.preset,
        codex_cycles=launch_config.codex_cycles if _codex_tui_queue_workflow_supported(launch_config) else 0,
        direct_prompt_enabled=launch_config.direct_prompt_enabled,
        browser_e2e_followup_enable=launch_config.browser_e2e_followup_enable,
        pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
    )
    workspace_id = None
    configured_workspace = (
        launch_config.superset_workspace
        if launch_config.transport == "superset"
        else launch_config.cmux_workspace
    )
    if include_workspace_details:
        workspace_id = (
            None if launch_config.transport in {"tmux", "superset"} else resolve_workspace_id(runtime, launch_config)
        )
        configured_workspace = (
            launch_config.superset_workspace
            if launch_config.transport == "superset"
            else (launch_config.cmux_workspace or default_target_workspace_title(runtime, launch_config))
        )
    configured_workspace = configured_workspace or None
    route_is_plan = str(getattr(route, "command", "")).strip() == "plan"
    planning_prs_only = bool(getattr(route, "flags", {}).get("planning_prs"))
    reason = _inspection_reason(
        runtime,
        route=route,
        launch_config=launch_config,
        route_is_plan=route_is_plan,
        planning_prs_only=planning_prs_only,
    )
    return PlanAgentLaunchEvaluation(
        launch_config=launch_config,
        workflow=workflow,
        route_is_plan=route_is_plan,
        planning_prs_only=planning_prs_only,
        workspace_id=workspace_id,
        configured_workspace=configured_workspace,
        inspection_reason=reason,
    )


def _inspection_reason(
    runtime: Any,
    *,
    route: object,
    launch_config: PlanAgentLaunchConfig,
    route_is_plan: bool,
    planning_prs_only: bool,
) -> str:
    if not route_is_plan:
        return "not_plan_command"
    if planning_prs_only:
        return "planning_prs_only"
    if not launch_config.enabled:
        return "disabled"
    if launch_config.surface_transport_warning:
        return launch_config.surface_transport_warning
    if launch_config.transport == "omx" and launch_config.cli != "codex":
        return "unsupported_omx_cli"
    if launch_config.transport == "superset":
        if launch_config.cli != "codex":
            return "unsupported_superset_cli"
        if not launch_config.superset_workspace and not launch_config.superset_project:
            return "missing_superset_project"
    if _route_requests_ulw(route) and not _ulw_route_supported(launch_config=launch_config):
        return "unsupported_ulw_flag"
    if launch_config.transport == "cmux" and missing_required_cmux_context(runtime, launch_config):
        return "missing_cmux_context"
    return "awaiting_new_worktrees"
