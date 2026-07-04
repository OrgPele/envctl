from __future__ import annotations

from typing import Any, Callable

from envctl_engine.actions.action_test_execution_support import (
    build_test_action_execution_plan,
    emit_suite_spinner_decision,
    emit_test_execution_mode,
    print_test_execution_mode,
    resolve_suite_spinner_decision,
)
from envctl_engine.actions.action_test_interrupt_support import TestSuiteInterruptRegistry
from envctl_engine.actions.action_test_ship_on_pass_support import (
    run_ship_on_pass_for_targets,
    ship_on_pass_message,
)
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
from envctl_engine.actions.action_test_suite_execution_support import (
    execute_test_suites,
    render_command as _render_command,
)
from envctl_engine.runtime.command_router import Route

__all__ = [
    "_clean_failure_lines",
    "_failed_summary_artifact_available",
    "_format_failure_output_for_artifact",
    "_format_live_collection_status",
    "_format_live_progress_status",
    "_format_live_progress_status_with_counts",
    "_format_live_progress_status_without_total",
    "_live_failed_count",
    "_render_command",
    "_summarize_failure_output",
    "LiveTestProgressReporter",
    "ParallelTestProgressTracker",
    "TestSuiteInterruptRegistry",
    "run_test_action",
]


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
    ship_message, ship_message_code = ship_on_pass_message(
        route,
        dry_run=bool(route.flags.get("dry_run")),
        json_output=bool(route.flags.get("json")),
    )
    if ship_message_code != 0:
        return ship_message_code
    try:
        plan = build_test_action_execution_plan(orchestrator, route, targets)
    except RuntimeError as exc:
        print(str(exc))
        return 1
    execution_specs = plan.execution_specs
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
    suite_result = execute_test_suites(
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
    failures = suite_result.failures
    suite_outcomes = suite_result.outcomes

    summary_metadata = orchestrator._persist_test_summary_artifacts(
        route=route,
        targets=targets,
        outcomes=suite_outcomes,
    )

    if failures:
        fallback_failures: list[str] = []
        for item in sorted(suite_outcomes, key=lambda value: _outcome_int(value.get("index"))):
            if _outcome_int(item.get("returncode")) == 0:
                continue
            project_name = str(item.get("project_name", "")).strip()
            if project_name and _failed_summary_artifact_available(
                summary_metadata=summary_metadata,
                project_name=project_name,
            ):
                continue
            suite = str(item.get("suite", "suite"))
            index = _outcome_int(item.get("index"))
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
    if ship_message:
        return run_ship_on_pass_for_targets(orchestrator, route, targets, message=ship_message)
    return 0


def _outcome_int(value: object, *, default: int = 0) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float | str | bytes | bytearray):
        try:
            return int(value)
        except ValueError:
            return default
    return default
