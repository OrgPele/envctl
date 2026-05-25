from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import inspect
from pathlib import Path
import sys
import time
from typing import Any, Callable, ClassVar, Sequence

from envctl_engine.actions.action_test_execution_support import TestActionExecutionPlan
from envctl_engine.actions.action_test_interrupt_support import TestSuiteInterruptRegistry
from envctl_engine.actions.action_test_runner_failures import summarize_failure_output as _summarize_failure_output
from envctl_engine.actions.action_test_runner_progress import (
    LiveTestProgressReporter,
    ParallelTestProgressTracker,
)
from envctl_engine.actions.action_test_suite_event_support import TestSuiteEventEmitter
from envctl_engine.actions.action_test_suite_outcome_support import TestSuiteOutcomeRecorder
from envctl_engine.runtime.command_router import Route
from envctl_engine.test_output.symbols import format_duration
from envctl_engine.ui.path_links import render_path_for_terminal


@dataclass(frozen=True, slots=True)
class TestSuiteExecutionResult:
    failures: list[str]
    outcomes: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class TestSuiteRunLoop:
    __test__: ClassVar[bool] = False

    execution_specs: Sequence[Any]
    parallel: bool
    parallel_workers: int
    futures_module: Any
    run_spec: Callable[[Any], tuple[int, str]]
    failure_label: Callable[[Any], str]
    cancel_interrupted: Callable[[Any | None, dict[Any, Any]], None]
    shutdown_executor: Callable[[Any | None], None]

    def run(self) -> list[str]:
        executor: Any | None = None
        future_map: dict[Any, Any] = {}
        try:
            if self.parallel:
                pool = self.futures_module.ThreadPoolExecutor(max_workers=self.parallel_workers)
                executor = pool
                future_map = {pool.submit(self.run_spec, spec): spec for spec in self.execution_specs}
                return self._parallel_failures(future_map)
            return self._sequential_failures()
        except KeyboardInterrupt:
            self.cancel_interrupted(executor, future_map)
            raise
        finally:
            self.shutdown_executor(executor)

    def _parallel_failures(self, future_map: dict[Any, Any]) -> list[str]:
        failures: list[str] = []
        for future in self.futures_module.as_completed(future_map):
            execution = future_map[future]
            code, error = future.result()
            if code != 0:
                failures.append(self._failure_message(execution, error))
        return failures

    def _sequential_failures(self) -> list[str]:
        failures: list[str] = []
        for execution in self.execution_specs:
            code, error = self.run_spec(execution)
            if code != 0:
                failures.append(self._failure_message(execution, error))
                break
        return failures

    def _failure_message(self, execution: Any, error: str) -> str:
        return f"{self.failure_label(execution)}: {error or 'unknown test failure'}"


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


def render_command(command: list[str]) -> str:
    return " ".join(str(part) for part in command)


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
                failure_label=self._failure_label,
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
        self._announce_suite_start(execution, suite_label=suite_label, resolved_source=resolved_source)

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
        self._emit_suite_summary(execution, parsed)
        duration_ms = round((time.monotonic() - started_at) * 1000.0, 1)
        self._print_interactive_suite_finish(
            execution,
            suite_label=suite_label,
            completed=completed,
            parsed=parsed,
            duration_ms=duration_ms,
        )
        self.outcomes.record(execution, command=command, completed=completed, parsed=parsed, duration_ms=duration_ms)
        self.events.emit_finish(execution, command=command, completed=completed, duration_ms=duration_ms)
        self.interrupt_registry.clear_by_index(int(index))
        self._mark_finished(execution, completed=completed, parsed=parsed, duration_ms=duration_ms)

        if completed.returncode != 0:
            error = _summarize_failure_output(
                stdout=getattr(completed, "stdout", ""),
                stderr=getattr(completed, "stderr", ""),
                returncode=int(getattr(completed, "returncode", 1)),
            )
            return 1, error
        return 0, ""

    def _failure_label(self, execution: Any) -> str:
        return f"{execution.project_name}:{execution.spec.source} [{execution.index}/{len(self.execution_specs)}]"

    def _announce_suite_start(self, execution: Any, *, suite_label: str, resolved_source: str) -> None:
        index = execution.index
        spec = execution.spec
        project_name = execution.project_name
        status = self.orchestrator._test_execution_status(
            spec.command,
            args=execution.args,
            source=resolved_source,
            cwd=spec.cwd,
        )
        if self.plan.multi_project:
            status = f"{project_name}: {status}"
        status += f" [{index}/{len(self.execution_specs)}]" if len(self.execution_specs) > 1 else ""
        if not self.use_suite_spinner_group:
            self.orchestrator._emit_status(status)
        if self.interactive_command:
            started_label = f"{project_name} / {suite_label}" if self.plan.multi_project else suite_label
            if not self.use_suite_spinner_group:
                index_text = self.orchestrator._colorize(f"[{index}/{len(self.execution_specs)}]", fg="yellow")
                suite_text = self.orchestrator._colorize(started_label, fg="cyan", bold=True)
                state_text = self.orchestrator._colorize("started", fg="blue")
                print(f"  - {index_text} {suite_text} {state_text}")
                command_text = self.orchestrator._colorize(
                    render_command([*spec.command, *execution.args]), fg="gray"
                )
                cwd_text = self.orchestrator._colorize(
                    render_path_for_terminal(
                        str(Path(spec.cwd).resolve()),
                        env=getattr(self.orchestrator.runtime, "env", {}),
                        stream=sys.stdout,
                    ),
                    fg="gray",
                )
                print(f"      command: {command_text}")
                print(f"      cwd: {cwd_text}")

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

    def _emit_suite_summary(self, execution: Any, parsed: Any) -> None:
        if parsed is None:
            return
        counts_detected = bool(getattr(parsed, "counts_detected", False))
        if not (self.interactive_command and self.plan.parallel and self.plan.multi_project):
            if counts_detected:
                self.orchestrator._emit_status(
                    f"{execution.project_name} / {execution.spec.source} summary: "
                    f"{parsed.passed} passed, {parsed.failed} failed, {parsed.skipped} skipped"
                )
            else:
                self.orchestrator._emit_status(
                    f"{execution.project_name} / {execution.spec.source} summary: no parsed test counts"
                )
        self.events.emit_summary(execution, parsed=parsed)

    def _print_interactive_suite_finish(
        self,
        execution: Any,
        *,
        suite_label: str,
        completed: Any,
        parsed: Any,
        duration_ms: float,
    ) -> None:
        if not (self.interactive_command and not self.use_suite_spinner_group):
            return
        suite_status = "passed" if completed.returncode == 0 else "failed"
        finished_label = f"{execution.project_name} / {suite_label}" if self.plan.multi_project else suite_label
        counts_suffix = ""
        counts_detected = bool(getattr(parsed, "counts_detected", False)) if parsed is not None else False
        if parsed is not None and counts_detected:
            counts_suffix = f" • {parsed.passed} passed, {parsed.failed} failed, {parsed.skipped} skipped"
        icon = (
            self.orchestrator._colorize("✓", fg="green", bold=True)
            if completed.returncode == 0
            else self.orchestrator._colorize("✗", fg="red", bold=True)
        )
        index_text = self.orchestrator._colorize(f"[{execution.index}/{len(self.execution_specs)}]", fg="yellow")
        suite_text = self.orchestrator._colorize(finished_label, fg="cyan", bold=True)
        status_text = self.orchestrator._colorize(
            suite_status,
            fg=("green" if completed.returncode == 0 else "red"),
            bold=True,
        )
        print(
            f"  - {icon} {index_text} {suite_text} {status_text} "
            f"({format_duration(duration_ms / 1000.0)}){counts_suffix}"
        )
        if completed.returncode == 0 and parsed is not None and not counts_detected:
            print("      note: test command completed, but envctl could not extract test counts from the output.")

    def _mark_finished(self, execution: Any, *, completed: Any, parsed: Any, duration_ms: float) -> None:
        if self.use_suite_spinner_group:
            self.suite_spinner_group.mark_finished(
                execution,
                success=completed.returncode == 0,
                duration_text=format_duration(max(duration_ms / 1000.0, 0.0)),
                parsed=parsed,
            )
        else:
            self.progress_tracker.mark_finished(execution, success=completed.returncode == 0)

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
