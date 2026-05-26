from __future__ import annotations

import concurrent.futures
from pathlib import Path
import sys
from typing import Any

from envctl_engine.actions.action_test_plan_support import (
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
from envctl_engine.actions.action_test_runner import run_test_action as run_test_action_impl
from envctl_engine.actions.action_test_summary_support import (
    persist_test_summary_artifacts_for_orchestrator,
    print_test_suite_overview_for_orchestrator,
    suite_display_name,
)
from envctl_engine.actions.action_test_support import (
    TestExecutionSpec as _TestExecutionSpec,
    TestTargetContext,
    build_test_target_contexts,
)
from envctl_engine.actions.action_test_spinner_support import (
    TestSuiteSpinnerGroup as _TestSuiteSpinnerGroup,
    rich_progress_available as _rich_progress_available,
)
from envctl_engine.actions.project_action_support import test_action_extra_env as test_action_extra_env_impl
from envctl_engine.runtime.command_router import Route
from envctl_engine.test_output.test_runner import TestRunner
from envctl_engine.ui.spinner_service import resolve_spinner_policy


def _runtime(owner: Any) -> Any:
    return getattr(owner, "runtime")


def _compat_attr(name: str, fallback: Any) -> Any:
    module = sys.modules.get("envctl_engine.actions.action_command_orchestrator")
    if module is None:
        return fallback
    return getattr(module, name, fallback)


class ActionCommandTestFacadeMixin:
    def run_test_action(self, route: Route, targets: list[object]) -> int:
        return run_test_action_impl(
            self,
            route,
            targets,
            rich_progress_available=_compat_attr("_rich_progress_available", _rich_progress_available),
            suite_spinner_group_cls=_compat_attr("_TestSuiteSpinnerGroup", _TestSuiteSpinnerGroup),
            test_runner_cls=_compat_attr("TestRunner", TestRunner),
            futures_module=_compat_attr("concurrent", concurrent).futures,
            resolve_spinner_policy=_compat_attr("resolve_spinner_policy", resolve_spinner_policy),
        )

    def run_test_plan_action(self, route: Route, targets: list[object]) -> int:
        return _compat_attr("run_test_plan_action_for_targets_impl", run_test_plan_action_for_targets_impl)(
            self, route, targets
        )

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
    ) -> list[_TestExecutionSpec]:
        return _compat_attr("build_test_execution_specs_for_orchestrator", build_test_execution_specs_for_orchestrator)(
            self,
            route=route,
            targets=targets,
            target_contexts=target_contexts,
            include_backend=include_backend,
            include_frontend=include_frontend,
            run_all=run_all,
            untested=untested,
        )

    def test_action_extra_env(
        self,
        *,
        route: Route | None,
        target: object | None,
        suite_source: str,
    ) -> dict[str, str]:
        return test_action_extra_env_impl(
            runtime=_runtime(self),
            route=route,
            target=target,
            suite_source=suite_source,
            project_context_builder=getattr(self, "_migrate_project_context"),
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

    def _test_parallel_enabled(self, route: Route, specs: list[_TestExecutionSpec]) -> bool:
        rt = _runtime(self)
        return parallel_tests_enabled_impl(route, specs=specs, env=rt.env, config_raw=rt.config.raw)

    def _test_parallel_max_workers(self, route: Route, specs: list[_TestExecutionSpec]) -> int:
        rt = _runtime(self)
        return parallel_test_worker_count_impl(route, specs=specs, env=rt.env, config_raw=rt.config.raw)

    def _test_suite_spinner_policy_enabled(self, policy: Any) -> tuple[bool, str]:
        return suite_spinner_policy_enabled_impl(policy, env=getattr(_runtime(self), "env", {}))

    def _persist_test_summary_artifacts(
        self,
        *,
        route: Route,
        targets: list[object],
        outcomes: list[dict[str, object]],
    ) -> dict[str, dict[str, object]]:
        return _compat_attr(
            "persist_test_summary_artifacts_for_orchestrator",
            persist_test_summary_artifacts_for_orchestrator,
        )(self, route=route, targets=targets, outcomes=outcomes)

    def _print_test_suite_overview(
        self,
        outcomes: list[dict[str, object]],
        *,
        summary_metadata: dict[str, dict[str, object]] | None = None,
    ) -> None:
        _compat_attr("print_test_suite_overview_for_orchestrator", print_test_suite_overview_for_orchestrator)(
            self, outcomes, summary_metadata=summary_metadata
        )

    @staticmethod
    def _suite_display_name(source: str, *, failed_only: bool = False) -> str:
        return suite_display_name(source, failed_only=failed_only)

    def _test_target_contexts(self, targets: list[object]) -> list[TestTargetContext]:
        rt = _runtime(self)
        repo_root = Path(rt.config.base_dir)
        run_repo_root_raw = str(getattr(rt, "env", {}).get("RUN_REPO_ROOT", "")).strip()
        if run_repo_root_raw:
            candidate = Path(run_repo_root_raw).expanduser()
            if candidate.exists():
                repo_root = candidate.resolve()
        return build_test_target_contexts(targets, repo_root=repo_root)
