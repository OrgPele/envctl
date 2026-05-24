from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

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


@dataclass(frozen=True, slots=True)
class SuiteSpinnerDecision:
    policy: Any
    rich_progress_supported: bool
    rich_progress_error: str
    suite_policy_enabled: bool
    suite_policy_reason: str
    use_suite_spinner_group: bool
    reason: str


def build_test_action_execution_plan(orchestrator: Any, route: Any, targets: list[object]) -> TestActionExecutionPlan:
    run_all = bool(route.flags.get("all"))
    untested = bool(route.flags.get("untested"))
    failed_only = bool(route.flags.get("failed"))
    project_names = action_target_names(targets)
    orchestrator._emit_status(
        orchestrator._test_scope_status(project_names, run_all=run_all, untested=untested, failed=failed_only)
    )

    backend_flag = route.flags.get("backend")
    frontend_flag = route.flags.get("frontend")
    include_backend, include_frontend = orchestrator._test_service_selection(route, backend_flag, frontend_flag)

    target_contexts = orchestrator._test_target_contexts(targets)
    _ensure_test_prereqs(orchestrator, target_contexts)
    execution_specs = orchestrator._build_test_execution_specs(
        route=route,
        targets=targets,
        target_contexts=target_contexts,
        include_backend=include_backend,
        include_frontend=include_frontend,
        run_all=run_all,
        untested=untested,
    )

    parallel = orchestrator._test_parallel_enabled(route, execution_specs)
    parallel_workers = orchestrator._test_parallel_max_workers(route, execution_specs) if parallel else 1
    distinct_projects = {
        spec.project_name.strip().lower()
        for spec in execution_specs
        if spec.project_name.strip() and spec.project_name != "all-targets"
    }
    plan = TestActionExecutionPlan(
        run_all=run_all,
        untested=untested,
        failed_only=failed_only,
        interactive_command=bool(route.flags.get("interactive_command")),
        include_backend=include_backend,
        include_frontend=include_frontend,
        target_contexts=target_contexts,
        execution_specs=execution_specs,
        parallel=parallel,
        parallel_workers=parallel_workers,
        distinct_projects=distinct_projects,
    )
    emit_test_suite_plan(orchestrator.runtime, plan)
    return plan


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


def _ensure_test_prereqs(orchestrator: Any, target_contexts: list[TestTargetContext]) -> None:
    seen_roots: set[Path] = set()
    for context in target_contexts:
        project_root = Path(context.project_root).resolve()
        if project_root in seen_roots:
            continue
        seen_roots.add(project_root)
        ensure_repo_local_test_prereqs(project_root, emit_status=orchestrator._emit_status)


def _python_executable() -> str:
    import sys

    return sys.executable
