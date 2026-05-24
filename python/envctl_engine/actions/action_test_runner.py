from __future__ import annotations

from contextlib import nullcontext
import inspect
from pathlib import Path
import sys
import time
from typing import Any, Callable

from envctl_engine.actions.action_test_execution_support import (
    build_test_action_execution_plan,
    emit_suite_spinner_decision,
    emit_test_execution_mode,
    print_test_execution_mode,
    resolve_suite_spinner_decision,
)
from envctl_engine.actions.action_test_interrupt_support import TestSuiteInterruptRegistry
from envctl_engine.actions.action_test_runner_failures import (
    clean_failure_lines as _clean_failure_lines,
    failed_summary_artifact_available as _failed_summary_artifact_available,
    format_failure_output_for_artifact as _format_failure_output_for_artifact,
    summarize_failure_output as _summarize_failure_output,
)
from envctl_engine.actions.action_test_runner_progress import (
    LiveTestProgressReporter,
    ParallelTestProgressTracker,
    format_live_collection_status as _format_live_collection_status,
    format_live_progress_status as _format_live_progress_status,
    format_live_progress_status_with_counts as _format_live_progress_status_with_counts,
    format_live_progress_status_without_total as _format_live_progress_status_without_total,
    live_failed_count as _live_failed_count,
)
from envctl_engine.runtime.command_router import Route
from envctl_engine.test_output.symbols import format_duration
from envctl_engine.ui.path_links import render_path_for_terminal

__all__ = [
    "_clean_failure_lines",
    "_failed_summary_artifact_available",
    "_format_failure_output_for_artifact",
    "_format_live_collection_status",
    "_format_live_progress_status",
    "_format_live_progress_status_with_counts",
    "_format_live_progress_status_without_total",
    "_live_failed_count",
    "_summarize_failure_output",
    "LiveTestProgressReporter",
    "ParallelTestProgressTracker",
    "TestSuiteInterruptRegistry",
    "run_test_action",
]


def _render_command(command: list[str]) -> str:
    return " ".join(str(part) for part in command)


def run_test_action(
    orchestrator: Any,
    route: Route,
    targets: list[object],
    *,
    rich_progress_available: Callable[[], tuple[bool, str]],
    suite_spinner_group_cls: type[Any],
    test_runner_cls: type[Any],
    futures_module: Any,
    resolve_spinner_policy: Callable[[dict[str, str]], Any],
) -> int:
    rt = orchestrator.runtime
    try:
        plan = build_test_action_execution_plan(orchestrator, route, targets)
    except RuntimeError as exc:
        print(str(exc))
        return 1
    execution_specs = plan.execution_specs
    failed_only = plan.failed_only
    interactive_command = plan.interactive_command
    if not execution_specs:
        print("No test command configured. Set Backend test command or Frontend test command in envctl config.")
        return 1

    spinner_policy = resolve_spinner_policy(getattr(rt, "env", {}))
    suite_spinner_decision = resolve_suite_spinner_decision(
        interactive_command=interactive_command,
        spinner_policy=spinner_policy,
        rich_progress_available_fn=rich_progress_available,
        suite_policy_enabled_fn=orchestrator._test_suite_spinner_policy_enabled,
    )
    use_suite_spinner_group = suite_spinner_decision.use_suite_spinner_group
    emit_suite_spinner_decision(rt, suite_spinner_decision)
    if interactive_command and not use_suite_spinner_group:
        print(f"Suite spinner rows disabled: {suite_spinner_decision.reason}")
    emit_test_execution_mode(rt, plan, suite_spinner_group=use_suite_spinner_group)
    if interactive_command:
        print_test_execution_mode(orchestrator, plan)
    progress_tracker = ParallelTestProgressTracker(
        enabled=plan.parallel and not use_suite_spinner_group,
        total_suites=len(execution_specs),
        max_workers=plan.parallel_workers,
        multi_project=plan.multi_project,
        failed_only=failed_only,
        emit_status=orchestrator._emit_status,
        suite_display_name=orchestrator._suite_display_name,
    )

    if plan.parallel and not use_suite_spinner_group:
        orchestrator._emit_status(
            f"Running {len(execution_specs)} test suites in parallel (max {plan.parallel_workers} concurrent)..."
        )
        progress_tracker.emit_status(phase="queued")
    suite_spinner_group = suite_spinner_group_cls(
        execution_specs=execution_specs,
        enabled=use_suite_spinner_group,
        policy=spinner_policy,
        emit=getattr(rt, "_emit", None),
        suite_label_resolver=lambda source: orchestrator._suite_display_name(source, failed_only=failed_only),
        multi_project=plan.multi_project,
        env=getattr(rt, "env", {}),
    )

    suite_outcomes: list[dict[str, object]] = []
    interrupt_registry = TestSuiteInterruptRegistry(
        runtime=rt,
        emit_status=orchestrator._emit_status,
        execution_mode=plan.execution_mode,
    )

    def run_spec(execution: Any) -> tuple[int, str]:
        index = execution.index
        spec = execution.spec
        args = execution.args
        resolved_source = execution.resolved_source
        project_name = execution.project_name
        project_root = execution.project_root
        suite_label = orchestrator._suite_display_name(spec.source, failed_only=failed_only)
        status = orchestrator._test_execution_status(
            spec.command,
            args=args,
            source=resolved_source,
            cwd=spec.cwd,
        )
        if plan.multi_project:
            status = f"{project_name}: {status}"
        status += f" [{index}/{len(execution_specs)}]" if len(execution_specs) > 1 else ""
        if not use_suite_spinner_group:
            orchestrator._emit_status(status)
        if interactive_command:
            started_label = f"{project_name} / {suite_label}" if plan.multi_project else suite_label
            if not use_suite_spinner_group:
                index_text = orchestrator._colorize(f"[{index}/{len(execution_specs)}]", fg="yellow")
                suite_text = orchestrator._colorize(started_label, fg="cyan", bold=True)
                state_text = orchestrator._colorize("started", fg="blue")
                print(f"  - {index_text} {suite_text} {state_text}")
                command_text = orchestrator._colorize(_render_command([*spec.command, *args]), fg="gray")
                cwd_text = orchestrator._colorize(
                    render_path_for_terminal(
                        str(Path(spec.cwd).resolve()),
                        env=getattr(orchestrator.runtime, "env", {}),
                        stream=sys.stdout,
                    ),
                    fg="gray",
                )
                print(f"      command: {command_text}")
                print(f"      cwd: {cwd_text}")
        live_label = f"{project_name} / {suite_label}" if plan.multi_project else suite_label
        live_progress_reporter: LiveTestProgressReporter | None = None

        def emit_live_progress(current: int, total: int) -> None:
            if live_progress_reporter is not None:
                live_progress_reporter.emit(current, total)

        if use_suite_spinner_group:
            suite_spinner_group.mark_running(execution)
        else:
            progress_tracker.mark_running(execution)
        command = [*spec.command, *args]
        started_at = time.monotonic()
        rt._emit(  # type: ignore[attr-defined]
            "test.suite.start",
            suite=spec.source,
            index=index,
            total=len(execution_specs),
            command=command,
            cwd=str(spec.cwd),
            project=project_name,
            project_root=str(project_root),
        )

        selected_target = (
            execution.target_obj if execution.target_obj is not None else (targets[0] if targets else None)
        )
        env_extra = orchestrator.test_action_extra_env(
            route=route,
            target=selected_target,
            suite_source=spec.source,
        )
        env = orchestrator.action_env("test", targets, route=route, target=selected_target, extra=env_extra)

        def emit_test_event(event_name: str, data: dict[str, Any]) -> None:
            rt._emit(  # type: ignore[attr-defined]
                f"test.{event_name}",
                suite=spec.source,
                index=index,
                project=project_name,
                project_root=str(project_root),
                **data,
            )

        runner = test_runner_cls(
            rt,
            verbose=False,
            detailed=False,
            run_coverage=False,
            emit_callback=emit_test_event,
            render_output=not interactive_command,
        )
        live_progress_reporter = LiveTestProgressReporter(
            label=live_label,
            emit_status=orchestrator._emit_status,
            parsed_provider=lambda: runner.last_result,
            spinner_progress=(
                (lambda status_text: suite_spinner_group.mark_progress(execution, status_text=status_text))
                if use_suite_spinner_group
                else None
            ),
        )
        run_test_kwargs: dict[str, object] = {
            "cwd": spec.cwd,
            "env": env,
            "timeout": 300.0,
        }
        run_test_parameters = inspect.signature(runner.run_tests).parameters
        if interactive_command and "progress_callback" in run_test_parameters:
            run_test_kwargs["progress_callback"] = emit_live_progress
        if "process_started_callback" in run_test_parameters:
            run_test_kwargs["process_started_callback"] = lambda pid: interrupt_registry.register_started_suite(
                execution, int(pid)
            )

        completed = runner.run_tests(command, **run_test_kwargs)
        parsed = runner.last_result
        if parsed is not None:
            counts_detected = bool(getattr(parsed, "counts_detected", False))
            if not (interactive_command and plan.parallel and plan.multi_project):
                if counts_detected:
                    orchestrator._emit_status(
                        f"{project_name} / {spec.source} summary: "
                        f"{parsed.passed} passed, {parsed.failed} failed, {parsed.skipped} skipped"
                    )
                else:
                    orchestrator._emit_status(f"{project_name} / {spec.source} summary: no parsed test counts")
            rt._emit(  # type: ignore[attr-defined]
                "test.suite.summary",
                suite=spec.source,
                index=index,
                total=len(execution_specs),
                project=project_name,
                project_root=str(project_root),
                counts_detected=counts_detected,
                passed=(parsed.passed if counts_detected else None),
                failed=(parsed.failed if counts_detected else None),
                skipped=(parsed.skipped if counts_detected else None),
                errors=(parsed.errors if counts_detected else None),
                total_tests=(parsed.total if counts_detected else None),
            )
        duration_ms = round((time.monotonic() - started_at) * 1000.0, 1)
        if interactive_command and not use_suite_spinner_group:
            suite_status = "passed" if completed.returncode == 0 else "failed"
            finished_label = f"{project_name} / {suite_label}" if plan.multi_project else suite_label
            counts_suffix = ""
            counts_detected = bool(getattr(parsed, "counts_detected", False)) if parsed is not None else False
            if parsed is not None and counts_detected:
                counts_suffix = f" • {parsed.passed} passed, {parsed.failed} failed, {parsed.skipped} skipped"
            icon = (
                orchestrator._colorize("✓", fg="green", bold=True)
                if completed.returncode == 0
                else orchestrator._colorize("✗", fg="red", bold=True)
            )
            index_text = orchestrator._colorize(f"[{index}/{len(execution_specs)}]", fg="yellow")
            suite_text = orchestrator._colorize(finished_label, fg="cyan", bold=True)
            status_text = orchestrator._colorize(
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
        suite_outcomes.append(
            {
                "suite": spec.source,
                "index": index,
                "project_name": project_name,
                "project_root": str(project_root),
                "command": command,
                "cwd": str(spec.cwd),
                "returncode": completed.returncode,
                "duration_ms": duration_ms,
                "parsed": parsed,
                "failed_only": failed_only,
                "failure_summary": _summarize_failure_output(
                    stdout=getattr(completed, "stdout", ""),
                    stderr=getattr(completed, "stderr", ""),
                    returncode=int(getattr(completed, "returncode", 1)),
                )
                if completed.returncode != 0
                else "",
                "failure_details": _format_failure_output_for_artifact(
                    stdout=getattr(completed, "stdout", ""),
                    stderr=getattr(completed, "stderr", ""),
                    returncode=int(getattr(completed, "returncode", 1)),
                )
                if completed.returncode != 0
                else "",
            }
        )
        rt._emit(  # type: ignore[attr-defined]
            "test.suite.finish",
            suite=spec.source,
            index=index,
            total=len(execution_specs),
            command=command,
            cwd=str(spec.cwd),
            returncode=completed.returncode,
            duration_ms=duration_ms,
            project=project_name,
            project_root=str(project_root),
        )
        interrupt_registry.clear_by_index(int(index))
        if use_suite_spinner_group:
            suite_spinner_group.mark_finished(
                execution,
                success=completed.returncode == 0,
                duration_text=format_duration(max(duration_ms / 1000.0, 0.0)),
                parsed=parsed,
            )
        else:
            progress_tracker.mark_finished(execution, success=completed.returncode == 0)

        if completed.returncode != 0:
            error = _summarize_failure_output(
                stdout=getattr(completed, "stdout", ""),
                stderr=getattr(completed, "stderr", ""),
                returncode=int(getattr(completed, "returncode", 1)),
            )
            return 1, error
        return 0, ""

    failures: list[str] = []
    suite_spinner_context = suite_spinner_group if use_suite_spinner_group else nullcontext(suite_spinner_group)
    with suite_spinner_context:
        executor: Any | None = None
        future_map: dict[object, Any] = {}
        try:
            if plan.parallel:
                executor = futures_module.ThreadPoolExecutor(max_workers=plan.parallel_workers)
                future_map = {executor.submit(run_spec, spec): spec for spec in execution_specs}
                for future in futures_module.as_completed(future_map):
                    execution = future_map[future]
                    code, error = future.result()
                    if code != 0:
                        label = (
                            f"{execution.project_name}:{execution.spec.source} "
                            f"[{execution.index}/{len(execution_specs)}]"
                        )
                        failures.append(f"{label}: {error or 'unknown test failure'}")
            else:
                for spec in execution_specs:
                    code, error = run_spec(spec)
                    if code != 0:
                        label = f"{spec.project_name}:{spec.spec.source} [{spec.index}/{len(execution_specs)}]"
                        failures.append(f"{label}: {error or 'unknown test failure'}")
                        break
        except KeyboardInterrupt:
            queued_cancelled = 0
            executor_shutdown = getattr(executor, "shutdown", None) if executor is not None else None
            if plan.parallel and callable(executor_shutdown):
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
            interrupt_registry.cleanup_interrupted_suites(queued_cancelled=queued_cancelled)
            raise
        finally:
            executor_shutdown = getattr(executor, "shutdown", None) if executor is not None else None
            if plan.parallel and callable(executor_shutdown):
                try:
                    executor_shutdown(
                        wait=not interrupt_registry.interrupt_received,
                        cancel_futures=interrupt_registry.interrupt_received,
                    )
                except TypeError:
                    executor_shutdown(wait=not interrupt_registry.interrupt_received)

    summary_metadata = orchestrator._persist_test_summary_artifacts(
        route=route,
        targets=targets,
        outcomes=suite_outcomes,
    )

    if failures:
        fallback_failures: list[str] = []
        for item in sorted(suite_outcomes, key=lambda value: int(value.get("index", 0))):
            if int(item.get("returncode", 0) or 0) == 0:
                continue
            project_name = str(item.get("project_name", "")).strip()
            if project_name and _failed_summary_artifact_available(
                summary_metadata=summary_metadata,
                project_name=project_name,
            ):
                continue
            suite = str(item.get("suite", "suite"))
            index = int(item.get("index", 0) or 0)
            detail = str(item.get("failure_summary", "") or "").strip() or "unknown test failure"
            fallback_failures.append(f"{project_name}:{suite} [{index}/{len(execution_specs)}]: {detail}")
        message = "; ".join(fallback_failures or failures)
        if interactive_command:
            if fallback_failures:
                orchestrator._emit_status(f"Test command failed: {message}")
        else:
            print(f"test action failed: {message}")
        orchestrator._print_test_suite_overview(suite_outcomes, summary_metadata=summary_metadata)
        return 1
    orchestrator._print_test_suite_overview(suite_outcomes, summary_metadata=summary_metadata)
    if interactive_command:
        orchestrator._emit_status(f"Test command finished for {len(targets)} target(s)")
    else:
        print(f"Executed test action for {len(targets)} target(s).")
    return 0
