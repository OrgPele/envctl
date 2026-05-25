from __future__ import annotations

from typing import Any, cast

from envctl_engine.actions.project_action_domain import probe_dirty_worktree as probe_dirty_worktree  # noqa: F401
from envctl_engine.planning.plan_agent.cmux_transport import (  # noqa: F401
    launch_review_agent_terminal as launch_review_agent_terminal,
    review_agent_launch_readiness as review_agent_launch_readiness,
)
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.startup.startup_selection_support import (  # noqa: F401
    _tree_preselected_projects_from_state as _tree_preselected_projects_from_state_impl,
)
from envctl_engine.ui.dashboard.orchestrator_command_mixin import DashboardCommandMixin
from envctl_engine.ui.dashboard.orchestrator_failure_mixin import DashboardFailureDetailMixin
from envctl_engine.ui.dashboard.orchestrator_pr_mixin import DashboardPrFlowMixin
from envctl_engine.ui.dashboard.orchestrator_restart_mixin import DashboardRestartSelectionMixin
from envctl_engine.ui.dashboard.orchestrator_stop_mixin import DashboardStopScopeMixin
from envctl_engine.ui.dashboard.orchestrator_target_mixin import DashboardTargetSelectionMixin
from envctl_engine.ui.dashboard_loop_support import run_legacy_dashboard_loop
from envctl_engine.ui.textual.screens.selector import _run_selector_with_impl as _run_selector_with_impl  # noqa: F401


_REVIEW_TAB_OPEN_TOKEN = "__REVIEW_TAB_OPEN__"
_REVIEW_TAB_SKIP_TOKEN = "__REVIEW_TAB_SKIP__"
_REVIEW_TAB_LAUNCH_FLAG = "dashboard_review_tab_launch"


class DashboardOrchestrator(
    DashboardCommandMixin,
    DashboardFailureDetailMixin,
    DashboardTargetSelectionMixin,
    DashboardStopScopeMixin,
    DashboardPrFlowMixin,
    DashboardRestartSelectionMixin,
):
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def execute(self, route: Route) -> int:
        rt: Any = self.runtime
        state = rt._try_load_existing_state(  # type: ignore[attr-defined]
            mode=route.mode,
            strict_mode_match=rt._state_lookup_strict_mode_match(route),  # type: ignore[attr-defined]
        )
        if state is None:
            rt._emit("dashboard.snapshot.source", reason="reload-failed", mode=route.mode)  # type: ignore[attr-defined]
            print("No active run state found.")
            return 0
        rt._emit("dashboard.snapshot.source", reason="fresh-load", mode=state.mode, run_id=state.run_id)  # type: ignore[attr-defined]
        if rt.config.runtime_truth_mode == "strict" and rt._state_has_synthetic_services(state):  # type: ignore[attr-defined]
            rt._emit(  # type: ignore[attr-defined]
                "synthetic.execution.blocked",
                command="dashboard",
                reason_code="synthetic_state_detected",
            )
            rt._emit(  # type: ignore[attr-defined]
                "cutover.gate.fail_reason",
                gate="command_parity",
                reason="synthetic_state_detected",
                scope="dashboard",
            )
            print("Dashboard blocked: synthetic placeholder defaults detected.")
            return 1
        if rt._should_enter_dashboard_interactive(route):  # type: ignore[attr-defined]
            interactive_runner = getattr(rt, "_run_interactive_dashboard_loop", None)
            if callable(interactive_runner):
                return cast(int, interactive_runner(state))
            return self.run_interactive_dashboard_loop(state, rt)
        if bool(route.flags.get("interactive")) or bool(route.flags.get("dashboard_interactive")):
            print("Interactive dashboard requires a TTY; showing snapshot.")
        rt._print_dashboard_snapshot(state)  # type: ignore[attr-defined]
        return 0

    def run_interactive_dashboard_loop(self, state: RunState, rt: object) -> int:
        runtime_any = cast(Any, rt)
        return run_legacy_dashboard_loop(
            state=state,
            runtime=runtime_any,
            fallback_handler=self._run_interactive_command,
            sanitize=self._sanitize_interactive_input,
        )
