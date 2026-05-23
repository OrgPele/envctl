from __future__ import annotations

import concurrent.futures
from pathlib import Path
import sys
from typing import Any, Callable, Mapping

from envctl_engine.actions.action_command_support import service_types_from_route_services
from envctl_engine.actions.action_command_execution_support import (
    execute_action_command as execute_action_command_impl,
)
from envctl_engine.actions.action_git_command_support import (
    run_commit_action_with_owner,
    run_pr_action_with_owner,
    run_review_action_with_owner,
    run_ship_action_with_owner,
)
from envctl_engine.actions.action_migrate_support import (
    migrate_backend_cwd as migrate_backend_cwd_impl,
    migrate_project_context as migrate_project_context_impl,
    migrate_requirements_for_target as migrate_requirements_for_target_impl,
    MigrateProjectContext as _MigrateProjectContext,
)
from envctl_engine.actions.action_migrate_execution_support import (
    run_migrate_action_with_owner,
)
from envctl_engine.actions.action_runtime_facade import ActionRuntimeFacade
from envctl_engine.actions.action_output_support import (
    action_colors_enabled as action_colors_enabled_impl,
    colorize_action_text as colorize_action_text_impl,
)
from envctl_engine.actions.action_target_support import (
    ActionTargetContext,
    execute_targeted_action,
    projects_for_services as projects_for_services_impl,
    resolve_action_targets as resolve_action_targets_impl,
)
from envctl_engine.actions.action_spinner_support import (
    install_action_spinner_status_bridge as install_action_spinner_status_bridge_impl,
    noop_restore as noop_restore_impl,
)
from envctl_engine.actions.action_test_summary_support import (
    new_test_results_run_dir_path as new_test_results_run_dir_path_impl,
    persist_test_summary_artifacts_for_orchestrator,
    print_test_suite_overview_for_orchestrator,
    short_failed_summary_path as short_failed_summary_path_impl,
    write_failed_tests_summary_for_orchestrator,
)
from envctl_engine.actions.action_test_plan_support import (
    additional_service_test_execution_specs_for_orchestrator,
    build_failed_test_execution_specs_for_orchestrator,
    build_test_execution_specs_for_orchestrator,
    command_start_status as command_start_status_impl,
    parallel_test_worker_count as parallel_test_worker_count_impl,
    parallel_tests_enabled as parallel_tests_enabled_impl,
    render_test_execution_status as render_test_execution_status_impl,
    render_test_scope_status as render_test_scope_status_impl,
    run_test_plan_action_for_targets as run_test_plan_action_for_targets_impl,
    select_test_services as select_test_services_impl,
    suite_spinner_policy_enabled as suite_spinner_policy_enabled_impl,
)
from envctl_engine.actions.action_project_report_owner import (
    persist_project_action_result_with_owner,
    project_action_failure_handler as project_action_failure_handler_impl,
    project_action_success_handler as project_action_success_handler_impl,
)
from envctl_engine.actions.project_action_env_support import (
    action_env as action_env_impl,
    action_extra_env as action_extra_env_impl,
    action_replacements as action_replacements_impl,
    migrate_action_env as migrate_action_env_impl,
    test_action_extra_env as test_action_extra_env_impl,
)
from envctl_engine.actions.project_action_execution_support import (
    run_project_action as run_project_action_impl,
)
from envctl_engine.actions.action_test_support import (
    TestExecutionSpec as _TestExecutionSpec,
    TestSuiteSpinnerGroup as _TestSuiteSpinnerGroup,
    TestTargetContext,
    build_test_target_contexts,
    rich_progress_available as _rich_progress_available,
)
from envctl_engine.actions.action_test_runner import run_test_action as run_test_action_impl
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
from envctl_engine.startup.service_bootstrap_domain import (
    _resolve_backend_env_contract,
)
from envctl_engine.state.models import RequirementsResult
from envctl_engine.test_output.test_runner import TestRunner
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI  # noqa: F401
from envctl_engine.ui.selection_support import interactive_selection_allowed, no_target_selected_message
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy


def _stdout_is_live_terminal() -> bool:
    streams = [getattr(sys, "stdout", None), getattr(sys, "__stdout__", None)]
    for stream in streams:
        if stream is None:
            continue
        try:
            if bool(getattr(stream, "isatty", lambda: False)()):
                return True
        except Exception:
            continue
    return False


class ActionCommandOrchestrator:
    def __init__(self, runtime: Any) -> None:
        self.runtime = ActionRuntimeFacade(runtime)
        self._migrate_env_contracts: dict[str, dict[str, object]] = {}
        self.execute_targeted_action_fn = execute_targeted_action
        self._deferred_post_action_output: Callable[[], None] | None = None

    @staticmethod
    def _short_failed_summary_path(*, run_dir: Path, project_name: str) -> Path:
        return short_failed_summary_path_impl(run_dir=run_dir, project_name=project_name)

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

    def run_test_action(self, route: Route, targets: list[object]) -> int:
        return run_test_action_impl(
            self,
            route,
            targets,
            rich_progress_available=_rich_progress_available,
            suite_spinner_group_cls=_TestSuiteSpinnerGroup,
            test_runner_cls=TestRunner,
            futures_module=concurrent.futures,
            resolve_spinner_policy=resolve_spinner_policy,
        )

    def run_pr_action(self, route: Route, targets: list[object]) -> int:
        return run_pr_action_with_owner(self, route, targets, extra_env=self.action_extra_env(route))

    def run_commit_action(self, route: Route, targets: list[object]) -> int:
        return run_commit_action_with_owner(self, route, targets, extra_env=self.action_extra_env(route))

    def run_ship_action(self, route: Route, targets: list[object]) -> int:
        return run_ship_action_with_owner(self, route, targets, extra_env=self.action_extra_env(route))

    def run_test_plan_action(self, route: Route, targets: list[object]) -> int:
        return run_test_plan_action_for_targets_impl(self, route, targets)

    def run_review_action(self, route: Route, targets: list[object]) -> int:
        return run_review_action_with_owner(self, route, targets, extra_env=self.action_extra_env(route))

    def run_migrate_action(self, route: Route, targets: list[object]) -> int:
        return run_migrate_action_with_owner(self, route, targets, extra_env=self.action_extra_env(route))

    def _no_target_selected_message(self, route: Route) -> str:
        interactive_allowed = self._interactive_selection_allowed(route)
        return no_target_selected_message(route.command, route=route, interactive_allowed=interactive_allowed)

    @staticmethod
    def _service_types_from_route_services(route: Route) -> set[str]:
        return service_types_from_route_services(route)

    def _test_service_selection(
        self,
        route: Route,
        backend_flag: object,
        frontend_flag: object,
    ) -> tuple[bool, bool]:
        return select_test_services_impl(route, backend_flag, frontend_flag)

    def _build_test_execution_specs(
        self,
        *,
        route: Route,
        targets: list[object],
        target_contexts: list[TestTargetContext],
        include_backend: bool,
        include_frontend: bool,
        run_all: bool,
        untested: bool,
    ) -> list["_TestExecutionSpec"]:
        return build_test_execution_specs_for_orchestrator(
            self,
            route=route,
            targets=targets,
            target_contexts=target_contexts,
            include_backend=include_backend,
            include_frontend=include_frontend,
            run_all=run_all,
            untested=untested,
        )

    def _additional_service_test_execution_specs(
        self,
        *,
        route: Route,
        targets: list[object],
        target_contexts: list[TestTargetContext],
    ) -> list["_TestExecutionSpec"]:
        return additional_service_test_execution_specs_for_orchestrator(
            self,
            route=route,
            targets=targets,
            target_contexts=target_contexts,
        )

    def _build_failed_test_execution_specs(
        self,
        *,
        route: Route,
        target_contexts: list[TestTargetContext],
    ) -> list["_TestExecutionSpec"]:
        return build_failed_test_execution_specs_for_orchestrator(
            self,
            route=route,
            target_contexts=target_contexts,
        )

    def run_project_action(
        self,
        route: Route,
        targets: list[object],
        *,
        command_name: str,
        env_key: str,
        default_command: list[str] | None,
        default_cwd: Path,
        default_append_project_path: bool,
        extra_env: Mapping[str, str],
    ) -> int:
        rt = self.runtime
        interactive_command = bool(route.flags.get("interactive_command"))
        return run_project_action_impl(
            runtime=rt,
            route=route,
            targets=targets,
            command_name=command_name,
            env_key=env_key,
            default_command=default_command,
            default_cwd=default_cwd,
            default_append_project_path=default_append_project_path,
            extra_env=extra_env,
            action_replacements_builder=self.action_replacements,
            action_env_builder=self.action_env,
            emit_status=self._emit_status,
            success_handler=self._project_action_success_handler(command_name, route.mode, interactive_command),
            failure_handler=self._project_action_failure_handler(command_name, route.mode),
            stdout_is_live_terminal=_stdout_is_live_terminal,
            execute_targeted_action_fn=execute_targeted_action,
        )

    def action_replacements(
        self,
        targets: list[object],
        *,
        target: object | None,
    ) -> dict[str, str]:
        return action_replacements_impl(
            runtime=self.runtime,
            targets=targets,
            target=target,
        )

    def action_env(
        self,
        command_name: str,
        targets: list[object],
        *,
        route: Route | None = None,
        target: object | None,
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        return action_env_impl(
            runtime=self.runtime,
            command_name=command_name,
            targets=targets,
            route=route,
            target=target,
            extra=extra,
        )

    def test_action_extra_env(
        self,
        *,
        route: Route | None,
        target: object | None,
        suite_source: str,
    ) -> dict[str, str]:
        return test_action_extra_env_impl(
            runtime=self.runtime,
            route=route,
            target=target,
            suite_source=suite_source,
            project_context_builder=self._migrate_project_context,
        )

    @staticmethod
    def action_extra_env(route: Route) -> dict[str, str]:
        return action_extra_env_impl(route)

    def migrate_action_env(
        self,
        *,
        targets: list[object],
        route: Route | None,
        target: object | None,
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        return migrate_action_env_impl(
            runtime=self.runtime,
            targets=targets,
            route=route,
            target=target,
            extra=extra,
            migrate_env_contracts=self._migrate_env_contracts,
            base_env_builder=self.action_env,
            backend_cwd=self._migrate_backend_cwd,
            requirements_for_target=self._migrate_requirements_for_target,
            project_context_builder=self._migrate_project_context,
            contract_context_builder=lambda project_name, target_root: _MigrateProjectContext(
                name=project_name,
                root=target_root,
                ports={},
            ),
            resolve_backend_env_contract=_resolve_backend_env_contract,
        )

    @staticmethod
    def _migrate_backend_cwd(target_root: Path) -> Path:
        return migrate_backend_cwd_impl(target_root)

    def _migrate_requirements_for_target(
        self,
        *,
        route: Route | None,
        project_name: str,
    ) -> RequirementsResult | None:
        return migrate_requirements_for_target_impl(runtime=self.runtime, route=route, project_name=project_name)

    @staticmethod
    def _migrate_project_context(
        *,
        project_name: str,
        project_root: Path,
        requirements: RequirementsResult,
    ) -> _MigrateProjectContext:
        return migrate_project_context_impl(
            project_name=project_name,
            project_root=project_root,
            requirements=requirements,
        )
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

    def _project_action_success_handler(
        self,
        command_name: str,
        mode: str,
        interactive_command: bool,
    ) -> Callable[[ActionTargetContext, Any], None] | None:
        return project_action_success_handler_impl(self, command_name, mode, interactive_command)

    def _project_action_failure_handler(
        self,
        command_name: str,
        mode: str,
    ) -> Callable[[ActionTargetContext, str], None]:
        return project_action_failure_handler_impl(self, command_name, mode)

    def _persist_project_action_result(
        self,
        *,
        command_name: str,
        mode: str,
        project_name: str,
        status: str,
        error_output: str,
        extra_entry: Mapping[str, object] | None = None,
    ) -> None:
        persist_project_action_result_with_owner(
            self,
            command_name=command_name,
            mode=mode,
            project_name=project_name,
            status=status,
            error_output=error_output,
            extra_entry=extra_entry,
        )

    def _clear_dashboard_pr_cache(self) -> None:
        runtime_raw = self.runtime.raw_runtime
        cache = getattr(runtime_raw, "_dashboard_pr_url_cache", None)
        if isinstance(cache, dict):
            cache.clear()

    def _colors_enabled(self) -> bool:
        return action_colors_enabled_impl(self.runtime)

    def _colorize(self, text: str, *, fg: str | None = None, bold: bool = False, dim: bool = False) -> str:
        return colorize_action_text_impl(
            text,
            enabled=self._colors_enabled(),
            fg=fg,
            bold=bold,
            dim=dim,
        )

    @staticmethod
    def _command_start_status(command_name: str, targets: list[object]) -> str:
        return command_start_status_impl(command_name, targets)

    @staticmethod
    def _test_scope_status(project_names: list[str], *, run_all: bool, untested: bool, failed: bool) -> str:
        return render_test_scope_status_impl(project_names, run_all=run_all, untested=untested, failed=failed)

    @staticmethod
    def _test_execution_status(command: list[str], *, args: list[str], source: str, cwd: Path) -> str:
        return render_test_execution_status_impl(command, args=args, source=source, cwd=cwd)

    def _test_parallel_enabled(self, route: Route, specs: list["_TestExecutionSpec"]) -> bool:
        rt = self.runtime
        return parallel_tests_enabled_impl(route, specs=specs, env=rt.env, config_raw=rt.config.raw)  # type: ignore[attr-defined]

    def _test_parallel_max_workers(self, route: Route, specs: list["_TestExecutionSpec"]) -> int:
        rt = self.runtime
        return parallel_test_worker_count_impl(route, specs=specs, env=rt.env, config_raw=rt.config.raw)  # type: ignore[attr-defined]

    def _test_suite_spinner_policy_enabled(self, policy: Any) -> tuple[bool, str]:
        rt = self.runtime
        return suite_spinner_policy_enabled_impl(policy, env=getattr(rt, "env", {}))

    def _persist_test_summary_artifacts(
        self,
        *,
        route: Route,
        targets: list[object],
        outcomes: list[dict[str, object]],
    ) -> dict[str, dict[str, object]]:
        return persist_test_summary_artifacts_for_orchestrator(self, route=route, targets=targets, outcomes=outcomes)

    def _new_test_results_run_dir(self, run_id: str) -> Path:
        return new_test_results_run_dir_path_impl(self.runtime, run_id)

    def _print_test_suite_overview(
        self,
        outcomes: list[dict[str, object]],
        *,
        summary_metadata: dict[str, dict[str, object]] | None = None,
    ) -> None:
        print_test_suite_overview_for_orchestrator(self, outcomes, summary_metadata=summary_metadata)

    def _write_failed_tests_summary(
        self,
        *,
        run_dir: Path,
        project_name: str,
        project_root: Path,
        outcomes: list[dict[str, object]],
        previous_entry: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return write_failed_tests_summary_for_orchestrator(
            self,
            run_dir=run_dir,
            project_name=project_name,
            project_root=project_root,
            outcomes=outcomes,
            previous_entry=previous_entry,
        )

    @staticmethod
    def _suite_display_name(source: str, *, failed_only: bool = False) -> str:
        from envctl_engine.actions.action_test_summary_support import suite_display_name

        return suite_display_name(source, failed_only=failed_only)

    def _test_target_contexts(self, targets: list[object]) -> list[TestTargetContext]:
        rt = self.runtime
        repo_root = Path(rt.config.base_dir)  # type: ignore[attr-defined]
        run_repo_root_raw = str(getattr(rt, "env", {}).get("RUN_REPO_ROOT", "")).strip()  # type: ignore[attr-defined]
        if run_repo_root_raw:
            candidate = Path(run_repo_root_raw).expanduser()
            if candidate.exists():
                repo_root = candidate.resolve()
        return build_test_target_contexts(targets, repo_root=repo_root)
