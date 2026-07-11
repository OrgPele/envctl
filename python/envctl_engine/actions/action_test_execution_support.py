from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ClassVar

from envctl_engine.actions.actions_test import ensure_repo_local_test_prereqs
from envctl_engine.actions.action_target_support import action_target_names
from envctl_engine.actions.action_test_support_models import TestExecutionSpec, TestTargetContext


@dataclass(frozen=True, slots=True)
class TestActionExecutionPlan:
    run_all: bool
    untested: bool
    failed_only: bool
    interactive_command: bool
    include_backend: bool
    include_frontend: bool
    target_contexts: list[TestTargetContext]
    execution_specs: list[TestExecutionSpec]
    parallel: bool
    parallel_workers: int
    distinct_projects: set[str]

    @property
    def execution_mode(self) -> str:
        return "parallel" if self.parallel else "sequential"

    @property
    def multi_project(self) -> bool:
        return len(self.distinct_projects) > 1

    @property
    def missing_execution_specs_message(self) -> str:
        if self.untested and not self.target_contexts:
            return (
                "No test command supports the all-untested scope. "
                "Configure a test-all-trees.sh action command or select projects explicitly."
            )
        return "No test command configured. Set Backend test command or Frontend test command in envctl config."


@dataclass(frozen=True, slots=True)
class SuiteSpinnerDecision:
    policy: Any
    rich_progress_supported: bool
    rich_progress_error: str
    suite_policy_enabled: bool
    suite_policy_reason: str
    use_suite_spinner_group: bool
    reason: str


@dataclass(frozen=True, slots=True)
class TestActionExecutionPlanBuilder:
    __test__: ClassVar[bool] = False

    orchestrator: Any
    route: Any
    targets: list[object]

    def build(self) -> TestActionExecutionPlan:
        self._emit_scope_status()
        include_backend, include_frontend = self._selected_services()
        target_contexts = self._target_contexts()
        _ensure_test_prereqs(
            self.orchestrator,
            target_contexts,
            aggregate_untested=self.untested and not target_contexts,
        )
        execution_specs = self._execution_specs(
            target_contexts=target_contexts,
            include_backend=include_backend,
            include_frontend=include_frontend,
        )
        parallel = self._parallel_enabled(execution_specs)
        plan = TestActionExecutionPlan(
            run_all=self.run_all,
            untested=self.untested,
            failed_only=self.failed_only,
            interactive_command=self.interactive_command,
            include_backend=include_backend,
            include_frontend=include_frontend,
            target_contexts=target_contexts,
            execution_specs=execution_specs,
            parallel=parallel,
            parallel_workers=self._parallel_workers(execution_specs, parallel=parallel),
            distinct_projects=self._distinct_projects(execution_specs),
        )
        emit_test_suite_plan(self.orchestrator.runtime, plan)
        return plan

    @property
    def run_all(self) -> bool:
        return bool(self.route.flags.get("all"))

    @property
    def untested(self) -> bool:
        return bool(self.route.flags.get("untested"))

    @property
    def failed_only(self) -> bool:
        return bool(self.route.flags.get("failed"))

    @property
    def interactive_command(self) -> bool:
        return bool(self.route.flags.get("interactive_command"))

    def _emit_scope_status(self) -> None:
        project_names = action_target_names(self.targets)
        self.orchestrator._emit_status(
            self.orchestrator._test_scope_status(
                project_names,
                run_all=self.run_all,
                untested=self.untested,
                failed=self.failed_only,
            )
        )

    def _selected_services(self) -> tuple[bool, bool]:
        return self.orchestrator._test_service_selection(
            self.route,
            self.route.flags.get("backend"),
            self.route.flags.get("frontend"),
        )

    def _target_contexts(self) -> list[TestTargetContext]:
        if self.untested and not self.targets:
            return []
        return self.orchestrator._test_target_contexts(self.targets)

    def _execution_specs(
        self,
        *,
        target_contexts: list[TestTargetContext],
        include_backend: bool,
        include_frontend: bool,
    ) -> list[TestExecutionSpec]:
        return self.orchestrator._build_test_execution_specs(
            route=self.route,
            targets=self.targets,
            target_contexts=target_contexts,
            include_backend=include_backend,
            include_frontend=include_frontend,
            run_all=self.run_all,
            untested=self.untested,
        )

    def _parallel_enabled(self, execution_specs: list[TestExecutionSpec]) -> bool:
        return self.orchestrator._test_parallel_enabled(self.route, execution_specs)

    def _parallel_workers(self, execution_specs: list[TestExecutionSpec], *, parallel: bool) -> int:
        if not parallel:
            return 1
        return self.orchestrator._test_parallel_max_workers(self.route, execution_specs)

    @staticmethod
    def _distinct_projects(execution_specs: list[TestExecutionSpec]) -> set[str]:
        return {
            spec.project_name.strip().lower()
            for spec in execution_specs
            if spec.project_name.strip() and spec.project_name != "all-targets"
        }


def build_test_action_execution_plan(orchestrator: Any, route: Any, targets: list[object]) -> TestActionExecutionPlan:
    return TestActionExecutionPlanBuilder(orchestrator=orchestrator, route=route, targets=targets).build()


def emit_test_suite_plan(runtime: Any, plan: TestActionExecutionPlan) -> None:
    runtime._emit(  # type: ignore[attr-defined]
        "test.suite.plan",
        suites=[spec.spec.source for spec in plan.execution_specs],
        total=len(plan.execution_specs),
        parallel=plan.parallel,
        projects=sorted(plan.distinct_projects),
    )


def resolve_suite_spinner_decision(
    *,
    interactive_command: bool,
    spinner_policy: Any,
    rich_progress_available_fn: Callable[[], tuple[bool, str]],
    suite_policy_enabled_fn: Callable[[Any], tuple[bool, str]],
) -> SuiteSpinnerDecision:
    rich_progress_supported, rich_progress_error = rich_progress_available_fn()
    suite_policy_enabled, suite_policy_reason = suite_policy_enabled_fn(spinner_policy)
    use_suite_spinner_group = bool(interactive_command and suite_policy_enabled and rich_progress_supported)
    reason = "enabled"
    if not interactive_command:
        reason = "non_interactive"
    elif not suite_policy_enabled:
        reason = f"suite_spinner_policy_disabled:{suite_policy_reason}"
    elif not rich_progress_supported:
        reason = "rich_progress_unavailable"
    return SuiteSpinnerDecision(
        policy=spinner_policy,
        rich_progress_supported=rich_progress_supported,
        rich_progress_error=rich_progress_error,
        suite_policy_enabled=suite_policy_enabled,
        suite_policy_reason=suite_policy_reason,
        use_suite_spinner_group=use_suite_spinner_group,
        reason=reason,
    )


def emit_suite_spinner_decision(runtime: Any, decision: SuiteSpinnerDecision) -> None:
    runtime._emit(  # type: ignore[attr-defined]
        "test.suite_spinner_group.policy",
        enabled=decision.use_suite_spinner_group,
        reason=decision.reason,
        backend=str(getattr(decision.policy, "backend", "")),
        rich_progress_supported=decision.rich_progress_supported,
        rich_progress_error=decision.rich_progress_error,
        python_executable=_python_executable(),
        suite_policy_reason=decision.suite_policy_reason,
    )


def emit_test_execution_mode(runtime: Any, plan: TestActionExecutionPlan, *, suite_spinner_group: bool) -> None:
    runtime._emit(  # type: ignore[attr-defined]
        "test.execution.mode",
        mode=plan.execution_mode,
        total=len(plan.execution_specs),
        projects=len(plan.distinct_projects) or 1,
        max_workers=plan.parallel_workers,
        suite_spinner_group=suite_spinner_group,
    )


def print_test_execution_mode(orchestrator: Any, plan: TestActionExecutionPlan) -> None:
    mode_color = "green" if plan.parallel else "yellow"
    if len(plan.distinct_projects) > 1:
        text = (
            f"Test execution mode: {plan.execution_mode} "
            f"({len(plan.execution_specs)} suites across {len(plan.distinct_projects)} projects)"
        )
    else:
        text = f"Test execution mode: {plan.execution_mode} ({len(plan.execution_specs)} suites)"
    print(orchestrator._colorize(text, fg=mode_color, bold=True))


def _ensure_test_prereqs(
    orchestrator: Any,
    target_contexts: list[TestTargetContext],
    *,
    aggregate_untested: bool,
) -> None:
    project_roots = [Path(context.project_root) for context in target_contexts]
    if aggregate_untested:
        project_roots.append(Path(orchestrator.runtime.config.base_dir))
    seen_roots: set[Path] = set()
    for root in project_roots:
        project_root = root.resolve()
        if project_root in seen_roots:
            continue
        seen_roots.add(project_root)
        ensure_repo_local_test_prereqs(project_root, emit_status=orchestrator._emit_status)


def _python_executable() -> str:
    import sys

    return sys.executable
