from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import inspect
from pathlib import Path
import time
from typing import Any

from envctl_engine.actions.action_test_execution_support import TestActionExecutionPlan
from envctl_engine.actions.action_test_interrupt_support import TestSuiteInterruptRegistry
from envctl_engine.actions.action_test_runner_failures import summarize_failure_output as _summarize_failure_output
from envctl_engine.actions.action_test_runner_progress import (
    LiveTestProgressReporter,
    ParallelTestProgressTracker,
)
from envctl_engine.actions.action_test_suite_event_support import TestSuiteEventEmitter
from envctl_engine.actions.action_test_suite_outcome_support import TestSuiteOutcomeRecorder
from envctl_engine.actions.action_test_suite_presentation import TestSuitePresenter, render_command as render_command
from envctl_engine.actions.action_test_suite_run_loop import TestSuiteRunLoop
from envctl_engine.runtime.command_router import Route


@dataclass(frozen=True, slots=True)
class TestSuiteExecutionResult:
    failures: list[str]
    outcomes: list[dict[str, object]]


def execute_test_suites(
    *,
    orchestrator: Any,
    route: Route,
    targets: list[object],
    plan: TestActionExecutionPlan,
    spinner_policy: Any,
    use_suite_spinner_group: bool,
    suite_spinner_group_cls: type[Any],
    test_runner_cls: type[Any],
    futures_module: Any,
) -> TestSuiteExecutionResult:
    executor = _TestSuiteExecutor(
        orchestrator=orchestrator,
        route=route,
        targets=targets,
        plan=plan,
        spinner_policy=spinner_policy,
        use_suite_spinner_group=use_suite_spinner_group,
        suite_spinner_group_cls=suite_spinner_group_cls,
        test_runner_cls=test_runner_cls,
        futures_module=futures_module,
    )
    return executor.run()


class _TestSuiteExecutor:
    def __init__(
        self,
        *,
        orchestrator: Any,
        route: Route,
        targets: list[object],
        plan: TestActionExecutionPlan,
        spinner_policy: Any,
        use_suite_spinner_group: bool,
        suite_spinner_group_cls: type[Any],
        test_runner_cls: type[Any],
        futures_module: Any,
    ) -> None:
        self.orchestrator = orchestrator
        self.route = route
        self.targets = targets
        self.plan = plan
        self.spinner_policy = spinner_policy
        self.use_suite_spinner_group = use_suite_spinner_group
        self.test_runner_cls = test_runner_cls
        self.futures_module = futures_module
        self.execution_specs = plan.execution_specs
        self.failed_only = plan.failed_only
        self.interactive_command = plan.interactive_command
        self.runtime = orchestrator.runtime
        self.progress_tracker = ParallelTestProgressTracker(
            enabled=plan.parallel and not use_suite_spinner_group,
            total_suites=len(self.execution_specs),
            max_workers=plan.parallel_workers,
            multi_project=plan.multi_project,
            failed_only=plan.failed_only,
            emit_status=orchestrator._emit_status,
            suite_display_name=orchestrator._suite_display_name,
        )
        self.suite_spinner_group = suite_spinner_group_cls(
            execution_specs=self.execution_specs,
            enabled=use_suite_spinner_group,
            policy=spinner_policy,
            emit=getattr(self.runtime, "_emit", None),
            suite_label_resolver=lambda source: orchestrator._suite_display_name(
                source, failed_only=plan.failed_only
            ),
            multi_project=plan.multi_project,
            env=getattr(self.runtime, "env", {}),
        )
        self.events = TestSuiteEventEmitter(runtime=self.runtime, total=len(self.execution_specs))
        self.outcomes = TestSuiteOutcomeRecorder(failed_only=self.failed_only)
        self.presenter = TestSuitePresenter(
            orchestrator=orchestrator,
            execution_specs=self.execution_specs,
            failed_only=self.failed_only,
            interactive_command=self.interactive_command,
            parallel=plan.parallel,
            multi_project=plan.multi_project,
            use_suite_spinner_group=use_suite_spinner_group,
            progress_tracker=self.progress_tracker,
            suite_spinner_group=self.suite_spinner_group,
            events=self.events,
        )
        self.interrupt_registry = TestSuiteInterruptRegistry(
            runtime=self.runtime,
            emit_status=orchestrator._emit_status,
            execution_mode=plan.execution_mode,
        )

    def run(self) -> TestSuiteExecutionResult:
        if self.plan.parallel and not self.use_suite_spinner_group:
            self.orchestrator._emit_status(
                f"Running {len(self.execution_specs)} test suites in parallel "
                f"(max {self.plan.parallel_workers} concurrent)..."
            )
            self.progress_tracker.emit_status(phase="queued")

        failures: list[str] = []
        suite_spinner_context = (
            self.suite_spinner_group if self.use_suite_spinner_group else nullcontext(self.suite_spinner_group)
        )
        with suite_spinner_context:
            failures = TestSuiteRunLoop(
                execution_specs=self.execution_specs,
                parallel=self.plan.parallel,
                parallel_workers=self.plan.parallel_workers,
                futures_module=self.futures_module,
                run_spec=self.run_spec,
                failure_label=self.presenter.failure_label,
                cancel_interrupted=self._cleanup_interrupted_parallel_suites,
                shutdown_executor=self._shutdown_executor,
            ).run()

        return TestSuiteExecutionResult(failures=failures, outcomes=self.outcomes.outcomes)

    def run_spec(self, execution: Any) -> tuple[int, str]:
        index = execution.index
        spec = execution.spec
        args = execution.args
        resolved_source = execution.resolved_source
        project_name = execution.project_name
        suite_label = self.orchestrator._suite_display_name(spec.source, failed_only=self.failed_only)
        self.presenter.announce_suite_start(execution, suite_label=suite_label, resolved_source=resolved_source)

        if self.use_suite_spinner_group:
            self.suite_spinner_group.mark_running(execution)
        else:
            self.progress_tracker.mark_running(execution)

        command = [*spec.command, *args]
        started_at = time.monotonic()
        self.events.emit_start(execution, command=command)

        selected_target = (
            execution.target_obj if execution.target_obj is not None else (self.targets[0] if self.targets else None)
        )
        env_extra = self.orchestrator.test_action_extra_env(
            route=self.route,
            target=selected_target,
            suite_source=spec.source,
        )
        env = self.orchestrator.action_env(
            "test",
            self.targets,
            route=self.route,
            target=selected_target,
            extra=env_extra,
        )
        runner = self._build_runner(execution, render_output=not self.interactive_command)
        live_label = f"{project_name} / {suite_label}" if self.plan.multi_project else suite_label
        live_progress_reporter = LiveTestProgressReporter(
            label=live_label,
            emit_status=self.orchestrator._emit_status,
            parsed_provider=lambda: runner.last_result,
            spinner_progress=(
                (lambda status_text: self.suite_spinner_group.mark_progress(execution, status_text=status_text))
                if self.use_suite_spinner_group
                else None
            ),
        )
        completed = runner.run_tests(
            command,
            **self._run_test_kwargs(
                execution,
                cwd=spec.cwd,
                env=env,
                live_progress_reporter=live_progress_reporter,
                runner=runner,
            ),
        )
        parsed = runner.last_result
        self.presenter.emit_suite_summary(execution, parsed)
        duration_ms = round((time.monotonic() - started_at) * 1000.0, 1)
        self.presenter.print_interactive_suite_finish(
            execution,
            suite_label=suite_label,
            completed=completed,
            parsed=parsed,
            duration_ms=duration_ms,
        )
        self.outcomes.record(execution, command=command, completed=completed, parsed=parsed, duration_ms=duration_ms)
        self.events.emit_finish(execution, command=command, completed=completed, duration_ms=duration_ms)
        self.interrupt_registry.clear_by_index(int(index))
        self.presenter.mark_finished(execution, completed=completed, parsed=parsed, duration_ms=duration_ms)

        if completed.returncode != 0:
            error = _summarize_failure_output(
                stdout=getattr(completed, "stdout", ""),
                stderr=getattr(completed, "stderr", ""),
                returncode=int(getattr(completed, "returncode", 1)),
            )
            return 1, error
        return 0, ""

    def _build_runner(self, execution: Any, *, render_output: bool) -> Any:
        def emit_test_event(event_name: str, data: dict[str, Any]) -> None:
            self.runtime._emit(  # type: ignore[attr-defined]
                f"test.{event_name}",
                suite=execution.spec.source,
                index=execution.index,
                project=execution.project_name,
                project_root=str(execution.project_root),
                **data,
            )

        return self.test_runner_cls(
            self.runtime,
            verbose=False,
            detailed=False,
            run_coverage=False,
            emit_callback=emit_test_event,
            render_output=render_output,
        )

    def _run_test_kwargs(
        self,
        execution: Any,
        *,
        cwd: Path,
        env: dict[str, str],
        live_progress_reporter: LiveTestProgressReporter,
        runner: Any,
    ) -> dict[str, object]:
        run_test_kwargs: dict[str, object] = {
            "cwd": cwd,
            "env": env,
            "timeout": 300.0,
        }
        run_test_parameters = inspect.signature(runner.run_tests).parameters
        if self.interactive_command and "progress_callback" in run_test_parameters:
            run_test_kwargs["progress_callback"] = live_progress_reporter.emit
        if "process_started_callback" in run_test_parameters:
            run_test_kwargs["process_started_callback"] = lambda pid: self.interrupt_registry.register_started_suite(
                execution, int(pid)
            )
        return run_test_kwargs

    def _cancel_queued_parallel_suites(self, *, executor: Any | None, future_map: dict[Any, Any]) -> int:
        queued_cancelled = 0
        executor_shutdown = getattr(executor, "shutdown", None) if executor is not None else None
        if self.plan.parallel and callable(executor_shutdown):
            try:
                executor_shutdown(wait=False, cancel_futures=True)
            except TypeError:
                executor_shutdown(wait=False)
            for future in future_map:
                cancelled = False
                try:
                    cancelled = bool(future.cancelled())
                except Exception:
                    cancelled = False
                if not cancelled:
                    try:
                        cancelled = bool(future.cancel())
                    except Exception:
                        cancelled = False
                if cancelled:
                    queued_cancelled += 1
        return queued_cancelled

    def _cleanup_interrupted_parallel_suites(self, executor: Any | None, future_map: dict[Any, Any]) -> None:
        queued_cancelled = self._cancel_queued_parallel_suites(executor=executor, future_map=future_map)
        self.interrupt_registry.cleanup_interrupted_suites(queued_cancelled=queued_cancelled)

    def _shutdown_executor(self, executor: Any | None) -> None:
        executor_shutdown = getattr(executor, "shutdown", None) if executor is not None else None
        if self.plan.parallel and callable(executor_shutdown):
            try:
                executor_shutdown(
                    wait=not self.interrupt_registry.interrupt_received,
                    cancel_futures=self.interrupt_registry.interrupt_received,
                )
            except TypeError:
                executor_shutdown(wait=not self.interrupt_registry.interrupt_received)
