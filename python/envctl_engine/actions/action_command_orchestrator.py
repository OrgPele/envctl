from __future__ import annotations

import concurrent.futures  # noqa: F401
from pathlib import Path
import sys  # noqa: F401
from typing import Any, Callable

from envctl_engine.actions.action_migrate_execution_support import run_migrate_action_with_owner  # noqa: F401
from envctl_engine.actions.action_test_plan_support import (  # noqa: F401
    build_test_execution_specs_for_orchestrator,
    run_test_plan_action_for_targets as run_test_plan_action_for_targets_impl,
)
from envctl_engine.actions.action_test_summary_support import (  # noqa: F401
    persist_test_summary_artifacts_for_orchestrator,
    print_test_suite_overview_for_orchestrator,
)
from envctl_engine.actions.action_test_support import (  # noqa: F401
    TestSuiteSpinnerGroup as _TestSuiteSpinnerGroup,
    rich_progress_available as _rich_progress_available,
)
from envctl_engine.actions.action_command_project_facade import _stdout_is_live_terminal  # noqa: F401
from envctl_engine.actions.action_command_execution_support import (
    execute_action_command as execute_action_command_impl,
)
from envctl_engine.actions.action_command_project_facade import ActionCommandProjectFacadeMixin
from envctl_engine.actions.action_command_test_facade import ActionCommandTestFacadeMixin
from envctl_engine.actions.action_runtime_facade import ActionRuntimeFacade
from envctl_engine.actions.action_target_support import (
    execute_targeted_action,
    projects_for_services as projects_for_services_impl,
    resolve_action_targets as resolve_action_targets_impl,
)
from envctl_engine.actions.action_spinner_support import (
    install_action_spinner_status_bridge as install_action_spinner_status_bridge_impl,
    noop_restore as noop_restore_impl,
)
from envctl_engine.actions.action_worktree_runner import (
    main_repo_root_for_worktree as main_repo_root_for_worktree_impl,
    repo_root_from_worktree_layout as repo_root_from_worktree_layout_impl,
    resolve_current_worktree_target as resolve_current_worktree_target_impl,
    run_delete_worktree_action as run_delete_worktree_action_impl,
    run_self_destruct_worktree_action as run_self_destruct_worktree_action_impl,
    spawn_self_destruct_helper as spawn_self_destruct_helper_impl,
)
from envctl_engine.runtime.command_router import Route
from envctl_engine.planning import discover_tree_projects
from envctl_engine.runtime.launcher_support import main_repo_root_for_linked_worktree
from envctl_engine.test_output.test_runner import TestRunner  # noqa: F401
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI  # noqa: F401
from envctl_engine.ui.selection_support import interactive_selection_allowed, no_target_selected_message
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy


class ActionCommandOrchestrator(ActionCommandProjectFacadeMixin, ActionCommandTestFacadeMixin):
    def __init__(self, runtime: Any) -> None:
        self.runtime = ActionRuntimeFacade(runtime)
        self._migrate_env_contracts: dict[str, dict[str, object]] = {}
        self.execute_targeted_action_fn = execute_targeted_action
        self._deferred_post_action_output: Callable[[], None] | None = None

    def execute(self, route: Route) -> int:
        return execute_action_command_impl(
            self,
            route,
            spinner_factory=spinner,
            resolve_spinner_policy_fn=resolve_spinner_policy,
            emit_spinner_policy_fn=emit_spinner_policy,
            use_spinner_policy_fn=use_spinner_policy,
        )

    def resolve_targets(self, route: Route, *, trees_only: bool) -> tuple[list[object], str | None]:
        return resolve_action_targets_impl(
            runtime=self.runtime,
            route=route,
            trees_only=trees_only,
            resolve_current_worktree_target=self._resolve_current_worktree_target,
            interactive_selection_allowed=self._interactive_selection_allowed,
            no_target_selected_message=self._no_target_selected_message,
        )

    def run_self_destruct_worktree_action(self, route: Route) -> int:
        return run_self_destruct_worktree_action_impl(self, route)

    def _resolve_current_worktree_target(self, *, require_configured_main_root: bool = False) -> object | None:
        return resolve_current_worktree_target_impl(
            runtime=self.runtime,
            require_configured_main_root=require_configured_main_root,
            current_cwd=Path.cwd,
            discover_tree_projects_fn=discover_tree_projects,
            main_repo_root_for_linked_worktree_fn=main_repo_root_for_linked_worktree,
            git_main_repo_root_for_worktree_fn=lambda worktree_root, trees_dir_name=None, **_kwargs: (
                self._main_repo_root_for_worktree(worktree_root, trees_dir_name=trees_dir_name)
            ),
        )

    def _main_repo_root_for_worktree(self, worktree_root: Path, *, trees_dir_name: str | None = None) -> Path | None:
        return main_repo_root_for_worktree_impl(
            worktree_root=worktree_root,
            runtime=self.runtime,
            trees_dir_name=trees_dir_name,
        )

    @staticmethod
    def _repo_root_from_worktree_layout(worktree_root: Path, trees_dir_name: str) -> Path | None:
        return repo_root_from_worktree_layout_impl(worktree_root, trees_dir_name)

    def _spawn_self_destruct_helper(self, *, repo_root: Path, trees_root: Path, worktree_root: Path) -> bool:
        return spawn_self_destruct_helper_impl(
            runtime=self.runtime,
            repo_root=repo_root,
            trees_root=trees_root,
            worktree_root=worktree_root,
        )

    def _interactive_selection_allowed(self, route: Route) -> bool:
        return interactive_selection_allowed(self.runtime.raw_runtime, route, allow_dashboard_override=True)

    def projects_for_services(self, service_targets: list[object]) -> list[str]:
        return projects_for_services_impl(self.runtime, service_targets)

    def _no_target_selected_message(self, route: Route) -> str:
        interactive_allowed = self._interactive_selection_allowed(route)
        return no_target_selected_message(route.command, route=route, interactive_allowed=interactive_allowed)

    @staticmethod
    def _noop_restore() -> None:
        return noop_restore_impl()

    def run_delete_worktree_action(self, route: Route) -> int:
        return run_delete_worktree_action_impl(self, route)

    def _emit_status(self, message: str) -> None:
        rt = self.runtime
        text = str(message).strip()
        if not text:
            return
        rt.emit("ui.status", message=text)

    def _install_action_spinner_status_bridge(
        self,
        *,
        command: str,
        op_id: str,
        active_spinner: Any,
    ) -> Callable[[], None]:
        return install_action_spinner_status_bridge_impl(
            runtime=self.runtime,
            command=command,
            op_id=op_id,
            active_spinner=active_spinner,
        )

    def _clear_dashboard_pr_cache(self) -> None:
        runtime_raw = self.runtime.raw_runtime
        cache = getattr(runtime_raw, "_dashboard_pr_url_cache", None)
        if isinstance(cache, dict):
            cache.clear()
