from __future__ import annotations

from collections import deque
from contextlib import nullcontext
import inspect
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable

from envctl_engine.runtime.command_router import Route
from envctl_engine.test_output.symbols import format_duration


def _render_command(command: list[str]) -> str:
    return " ".join(str(part) for part in command)


def _summarize_failure_output(*, stdout: object, stderr: object, returncode: int) -> str:
    chunks: list[str] = []
    for raw in (stderr, stdout):
        if not isinstance(raw, str):
            continue
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped:
                chunks.append(stripped)
        if chunks:
            break
    if not chunks:
        return f"exit:{returncode}"
    snippet = " | ".join(chunks[:3])
    if len(chunks) > 3:
        snippet += f" | +{len(chunks) - 3} more lines"
    return snippet


def _format_live_progress_status(label: str, current: int, total: int) -> str:
    return f"Running {label}... {current}/{total} tests complete"


def _format_live_progress_status_without_total(label: str, current: int, *, parsed: object | None) -> str:
    failed = min(max(_live_failed_count(parsed), 0), max(current, 0))
    passed = max(0, int(current) - failed)
    return f"Running {label}... {current} tests complete • {passed} passed, {failed} failed"


def _format_live_collection_status(label: str, discovered: int) -> str:
    return f"Collecting {label} tests... {discovered} discovered"


def _live_failed_count(parsed: object | None) -> int:
    if parsed is None:
        return 0
    failed = int(getattr(parsed, "failed", 0) or 0)
    errors = int(getattr(parsed, "errors", 0) or 0)
    failed_tests = len(getattr(parsed, "failed_tests", ()) or ())
    return max(failed + errors, failed_tests + errors)


def _format_live_progress_status_with_counts(label: str, current: int, total: int, *, parsed: object | None) -> str:
    failed = min(max(_live_failed_count(parsed), 0), max(current, 0))
    passed = max(0, int(current) - failed)
    return f"{_format_live_progress_status(label, current, total)} • {passed} passed, {failed} failed"


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
    run_all = bool(route.flags.get("all"))
    untested = bool(route.flags.get("untested"))
    failed_only = bool(route.flags.get("failed"))
    project_names = [str(getattr(target, "name")) for target in targets if hasattr(target, "name")]
    orchestrator._emit_status(
        orchestrator._test_scope_status(project_names, run_all=run_all, untested=untested, failed=failed_only)
    )
    interactive_command = bool(route.flags.get("interactive_command"))
    backend_flag = route.flags.get("backend")
    frontend_flag = route.flags.get("frontend")
    include_backend, include_frontend = orchestrator._test_service_selection(route, backend_flag, frontend_flag)

    raw = rt.env.get("ENVCTL_ACTION_TEST_CMD")  # type: ignore[attr-defined]
    target_contexts = orchestrator._test_target_contexts(targets)
    try:
        execution_specs = orchestrator._build_test_execution_specs(
            route=route,
            raw=raw,
            targets=targets,
            target_contexts=target_contexts,
            include_backend=include_backend,
            include_frontend=include_frontend,
            run_all=run_all,
            untested=untested,
        )
    except RuntimeError as exc:
        print(str(exc))
        return 1
    if not execution_specs:
        print("No test command configured. Set ENVCTL_ACTION_TEST_CMD or add utils/test-all-trees.sh.")
        return 1

    parallel = orchestrator._test_parallel_enabled(route, execution_specs)
    distinct_projects = {
        spec.project_name.strip().lower()
        for spec in execution_specs
        if spec.project_name.strip() and spec.project_name != "all-targets"
    }
    rt._emit(  # type: ignore[attr-defined]
        "test.suite.plan",
        suites=[spec.spec.source for spec in execution_specs],
        total=len(execution_specs),
        parallel=parallel,
        projects=sorted(distinct_projects),
    )
    execution_mode = "parallel" if parallel else "sequential"
    parallel_workers = orchestrator._test_parallel_max_workers(route, execution_specs) if parallel else 1
    multi_project = len(distinct_projects) > 1
    spinner_policy = resolve_spinner_policy(getattr(rt, "env", {}))
    rich_progress_supported, rich_progress_error = rich_progress_available()
    suite_policy_enabled, suite_policy_reason = orchestrator._test_suite_spinner_policy_enabled(spinner_policy)
    use_suite_spinner_group = bool(
        interactive_command
        and suite_policy_enabled
        and rich_progress_supported
    )
    suite_spinner_reason = "enabled"
    if not interactive_command:
        suite_spinner_reason = "non_interactive"
    elif not suite_policy_enabled:
        suite_spinner_reason = f"suite_spinner_policy_disabled:{suite_policy_reason}"
    elif not rich_progress_supported:
        suite_spinner_reason = "rich_progress_unavailable"
    rt._emit(  # type: ignore[attr-defined]
        "test.suite_spinner_group.policy",
        enabled=use_suite_spinner_group,
        reason=suite_spinner_reason,
        backend=str(getattr(spinner_policy, "backend", "")),
        rich_progress_supported=rich_progress_supported,
        rich_progress_error=rich_progress_error,
        python_executable=sys.executable,
        suite_policy_reason=suite_policy_reason,
    )
    if interactive_command and not use_suite_spinner_group:
        print(f"Suite spinner rows disabled: {suite_spinner_reason}")
    rt._emit(  # type: ignore[attr-defined]
        "test.execution.mode",
        mode=execution_mode,
        total=len(execution_specs),
        projects=len(distinct_projects) or 1,
        max_workers=parallel_workers,
        suite_spinner_group=use_suite_spinner_group,
    )
    if interactive_command:
        mode_color = "green" if parallel else "yellow"
        if len(distinct_projects) > 1:
            text = (
                f"Test execution mode: {execution_mode} "
                f"({len(execution_specs)} suites across {len(distinct_projects)} projects)"
            )
            print(orchestrator._colorize(text, fg=mode_color, bold=True))
        else:
            text = f"Test execution mode: {execution_mode} ({len(execution_specs)} suites)"
            print(orchestrator._colorize(text, fg=mode_color, bold=True))
    progress_lock = threading.Lock()
    progress_state = {
        "queued": len(execution_specs),
        "running": 0,
        "finished": 0,
        "running_labels": set(),
        "done_labels": deque(maxlen=4),
    }

    def render_labels(labels: list[str], *, max_items: int) -> str:
        if not labels:
            return "-"
        visible = labels[:max_items]
        if len(labels) > max_items:
            visible.append(f"+{len(labels) - max_items} more")
        return ", ".join(visible)

    def emit_parallel_progress_status(*, phase: str, execution: Any | None = None) -> None:
        if not parallel or use_suite_spinner_group:
            return
        prefix = (
            f"Tests progress: running {progress_state['running']}/{parallel_workers}, "
            f"finished {progress_state['finished']}/{len(execution_specs)}, "
            f"queued {progress_state['queued']}"
        )
        running_labels_sorted = sorted(str(label) for label in progress_state["running_labels"])
        done_labels_list = [str(label) for label in progress_state["done_labels"]]
        details = (
            f" • running: {render_labels(running_labels_sorted, max_items=3)}"
            f" • done: {render_labels(done_labels_list, max_items=3)}"
        )
        if execution is None:
            orchestrator._emit_status(f"{prefix}{details}")
            return
        suite_label = orchestrator._suite_display_name(execution.spec.source, failed_only=failed_only)
        descriptor = f"{execution.project_name} / {suite_label}" if multi_project else suite_label
        orchestrator._emit_status(f"{prefix} • {phase}: {descriptor}{details}")

    if parallel and not use_suite_spinner_group:
        orchestrator._emit_status(
            f"Running {len(execution_specs)} test suites in parallel (max {parallel_workers} concurrent)..."
        )
        emit_parallel_progress_status(phase="queued")
    suite_spinner_group = suite_spinner_group_cls(
        execution_specs=execution_specs,
        enabled=use_suite_spinner_group,
        policy=spinner_policy,
        emit=getattr(rt, "_emit", None),
            suite_label_resolver=lambda source: orchestrator._suite_display_name(source, failed_only=failed_only),
        multi_project=multi_project,
        env=getattr(rt, "env", {}),
    )

    suite_outcomes: list[dict[str, object]] = []

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
        if multi_project:
            status = f"{project_name}: {status}"
        status += f" [{index}/{len(execution_specs)}]" if len(execution_specs) > 1 else ""
        if not use_suite_spinner_group:
            orchestrator._emit_status(status)
        if interactive_command:
            started_label = f"{project_name} / {suite_label}" if multi_project else suite_label
            if not use_suite_spinner_group:
                index_text = orchestrator._colorize(f"[{index}/{len(execution_specs)}]", fg="yellow")
                suite_text = orchestrator._colorize(started_label, fg="cyan", bold=True)
                state_text = orchestrator._colorize("started", fg="blue")
                print(f"  - {index_text} {suite_text} {state_text}")
                command_text = orchestrator._colorize(_render_command([*spec.command, *args]), fg="gray")
                cwd_text = orchestrator._colorize(str(Path(spec.cwd).resolve()), fg="gray")
                print(f"      command: {command_text}")
                print(f"      cwd: {cwd_text}")
        progress_status: dict[str, object] = {
            "last": None,
            "current": None,
            "total": None,
            "running_started": False,
        }

        def emit_live_progress(current: int, total: int) -> None:
            live_label = f"{project_name} / {suite_label}" if multi_project else suite_label
            merged_current = progress_status["current"]
            merged_total = progress_status["total"]

            if current < 0:
                if bool(progress_status["running_started"]):
                    return
                snapshot = ("collecting", total)
                if progress_status["last"] == snapshot:
                    return
                progress_status["last"] = snapshot
                progress_status["total"] = total
                message = _format_live_collection_status(live_label, total)
                orchestrator._emit_status(message)
                if use_suite_spinner_group:
                    suite_spinner_group.mark_progress(execution, status_text=f"{total} discovered")
                return
            progress_status["running_started"] = True
            if total <= 0:
                merged_current = max(int(merged_current or 0), int(current))
                progress_status["current"] = merged_current
                snapshot = ("running", merged_current, 0)
                if progress_status["last"] == snapshot:
                    return
                progress_status["last"] = snapshot
                message = _format_live_progress_status_without_total(
                    live_label,
                    int(merged_current),
                    parsed=runner.last_result,
                )
                orchestrator._emit_status(message)
                if use_suite_spinner_group:
                    suite_spinner_group.mark_progress(
                        execution,
                        status_text=f"{int(merged_current)} complete • "
                        f"{max(0, int(merged_current) - min(max(_live_failed_count(runner.last_result), 0), max(int(merged_current), 0)))} passed, "
                        f"{min(max(_live_failed_count(runner.last_result), 0), max(int(merged_current), 0))} failed",
                    )
                return
            if int(current) == 0 and merged_current is not None and int(merged_current) > 0:
                merged_total = int(total)
                progress_status["total"] = merged_total
                snapshot = ("running", int(merged_current), merged_total)
                if progress_status["last"] == snapshot:
                    return
                progress_status["last"] = snapshot
                message = _format_live_progress_status_with_counts(
                    live_label,
                    int(merged_current),
                    merged_total,
                    parsed=runner.last_result,
                )
                orchestrator._emit_status(message)
                if use_suite_spinner_group:
                    suite_spinner_group.mark_progress(
                        execution,
                        status_text=(
                            f"{int(merged_current)}/{merged_total} complete • "
                            f"{max(0, int(merged_current) - min(max(_live_failed_count(runner.last_result), 0), max(int(merged_current), 0)))} passed, "
                            f"{min(max(_live_failed_count(runner.last_result), 0), max(int(merged_current), 0))} failed"
                        ),
                    )
                return
            merged_current = max(int(merged_current or 0), int(current))
            merged_total = int(total)
            progress_status["current"] = merged_current
            progress_status["total"] = merged_total
            snapshot = ("running", merged_current, merged_total)
            if progress_status["last"] == snapshot:
                return
            progress_status["last"] = snapshot
            message = _format_live_progress_status_with_counts(
                live_label,
                merged_current,
                merged_total,
                parsed=runner.last_result,
            )
            orchestrator._emit_status(message)
            if use_suite_spinner_group:
                suite_spinner_group.mark_progress(
                    execution,
                    status_text=(
                        f"{merged_current}/{merged_total} complete • "
                        f"{max(0, int(merged_current) - min(max(_live_failed_count(runner.last_result), 0), max(int(merged_current), 0)))} passed, "
                        f"{min(max(_live_failed_count(runner.last_result), 0), max(int(merged_current), 0))} failed"
                    ),
                )

        with progress_lock:
            if parallel:
                progress_state["queued"] = max(0, int(progress_state["queued"]) - 1)
                progress_state["running"] = int(progress_state["running"]) + 1
                descriptor = f"{project_name} / {suite_label}" if multi_project else suite_label
                progress_state["running_labels"].add(descriptor)
            if use_suite_spinner_group:
                suite_spinner_group.mark_running(execution)
            elif parallel:
                emit_parallel_progress_status(phase="running", execution=execution)
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
        env = orchestrator.action_env("test", targets, target=selected_target)

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

        completed = runner.run_tests(
            command,
            **(
                {
                    "cwd": spec.cwd,
                    "env": env,
                    "timeout": 300.0,
                    **(
                        {"progress_callback": emit_live_progress}
                        if interactive_command and "progress_callback" in inspect.signature(runner.run_tests).parameters
                        else {}
                    ),
                }
            ),
        )
        parsed = runner.last_result
        if parsed is not None:
            counts_detected = bool(getattr(parsed, "counts_detected", False))
            if not (interactive_command and parallel and multi_project):
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
                passed=parsed.passed,
                failed=parsed.failed,
                skipped=parsed.skipped,
                errors=parsed.errors,
                total_tests=parsed.total,
            )
        duration_ms = round((time.monotonic() - started_at) * 1000.0, 1)
        if interactive_command and not use_suite_spinner_group:
            suite_status = "passed" if completed.returncode == 0 else "failed"
            finished_label = f"{project_name} / {suite_label}" if multi_project else suite_label
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
            if completed.returncode != 0:
                failure_excerpt = _summarize_failure_output(
                    stdout=getattr(completed, "stdout", ""),
                    stderr=getattr(completed, "stderr", ""),
                    returncode=int(getattr(completed, "returncode", 1)),
                )
                print(f"      failure: {orchestrator._colorize(failure_excerpt, fg='red')}")
            elif parsed is not None and not counts_detected:
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
        with progress_lock:
            if parallel:
                progress_state["running"] = max(0, int(progress_state["running"]) - 1)
                progress_state["finished"] = int(progress_state["finished"]) + 1
                running_descriptor = f"{project_name} / {suite_label}" if multi_project else suite_label
                progress_state["running_labels"].discard(running_descriptor)
                done_status = "PASS" if completed.returncode == 0 else "FAIL"
                progress_state["done_labels"].append(f"{running_descriptor} ({done_status})")
                progress_state["queued"] = max(
                    0,
                    len(execution_specs) - int(progress_state["running"]) - int(progress_state["finished"]),
                )
            if use_suite_spinner_group:
                suite_spinner_group.mark_finished(
                    execution,
                    success=completed.returncode == 0,
                    duration_text=format_duration(max(duration_ms / 1000.0, 0.0)),
                    parsed=parsed,
                )
            elif parallel:
                emit_parallel_progress_status(phase="completed", execution=execution)

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
        if parallel:
            with futures_module.ThreadPoolExecutor(max_workers=parallel_workers) as pool:
                future_map = {pool.submit(run_spec, spec): spec for spec in execution_specs}
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

    summary_metadata = orchestrator._persist_test_summary_artifacts(
        route=route,
        targets=targets,
        outcomes=suite_outcomes,
    )

    if failures:
        message = "; ".join(failures)
        if interactive_command:
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
