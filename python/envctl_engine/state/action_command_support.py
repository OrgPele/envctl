from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast
from contextlib import contextmanager
import json
import signal
import threading

from envctl_engine.runtime.browser_diagnostics import build_runtime_diagnostics
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.docker_service_runtime import (
    refresh_container_log_snapshots,
    stop_container_log_followers,
)
from envctl_engine.shared.parsing import parse_float_or_none, parse_int
from envctl_engine.state.action_log_support import DEFAULT_LOG_ISSUE_LIMIT
from envctl_engine.state.models import RunState
from envctl_engine.state.project_runtime import (
    cwd_runtime_warnings,
    project_resolution_event_payload,
    resolve_requested_project_state,
)
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI


@dataclass
class StateActionReconciliation:
    failing_services: list[str] = field(default_factory=list)
    requirement_issues: list[dict[str, object]] = field(default_factory=list)
    recent_failures: list[str] = field(default_factory=list)
    reconciled: bool = False


@contextmanager
def _interrupt_log_follow_on_termination(enabled: bool):
    if not enabled or threading.current_thread() is not threading.main_thread():
        yield
        return
    previous: dict[signal.Signals, Any] = {}

    def interrupt(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    for signal_name in (signal.SIGHUP, signal.SIGTERM):
        previous[signal_name] = signal.getsignal(signal_name)
        signal.signal(signal_name, interrupt)
    try:
        yield
    finally:
        for signal_name, handler in previous.items():
            signal.signal(signal_name, handler)


class StateActionCommandRunner:
    def __init__(self, orchestrator: Any) -> None:
        self.orchestrator = orchestrator
        self.runtime = orchestrator.runtime
        self.command = ""
        self.state: RunState | None = None
        self.reconciliation = StateActionReconciliation()

    def execute(self, route: Route) -> int:
        self.command = route.command
        loaded_state = self.runtime.load_state(route)
        if loaded_state is None:
            print(f"No previous state found for '{self.command}'.")
            return 1

        current_state = self._resolve_project_state(route, loaded_state)
        if current_state is None:
            return 1
        self.state = current_state

        if self.command == "logs":
            return self._run_logs(route)
        if self.command == "clear-logs":
            return self._run_clear_logs(route)
        if self.command == "health":
            return self._run_health(route)
        if self.command == "errors":
            return self._run_errors(route)
        return self.runtime.unsupported_command(self.command)

    def _resolve_project_state(self, route: Route, state: RunState) -> RunState | None:
        if not route.projects:
            return state
        resolution = resolve_requested_project_state(
            state,
            route.projects,
            command=self.command,
            runtime=self.runtime.raw_runtime,
        )
        if not resolution.ok:
            self.orchestrator._emit(
                "state.project_resolution.failed",
                **project_resolution_event_payload(resolution, state, runtime=self.runtime.raw_runtime),
            )
            if bool(route.flags.get("json")):
                print(json.dumps(resolution.payload(), indent=2, sort_keys=True))
            else:
                print(self.orchestrator._project_mismatch_message(resolution.payload()))
            return None

        self.orchestrator._emit(
            "state.project_resolution.ok",
            **project_resolution_event_payload(resolution, state, runtime=self.runtime.raw_runtime),
        )
        if not bool(route.flags.get("all")) and resolution.state is not None:
            return resolution.state
        return state

    def _finish_action(self, code: int) -> int:
        assert self.state is not None
        self.orchestrator._emit_state_action_finish(command=self.command, state=self.state, code=code)
        return code

    def _ensure_reconciled(self) -> StateActionReconciliation:
        assert self.state is not None
        result = self.reconciliation
        if result.reconciled:
            return result

        result.failing_services = self.runtime.reconcile_state_truth(self.state)
        result.requirement_issues = self.runtime.requirement_truth_issues(self.state)
        result.recent_failures = (
            self.runtime.recent_failure_messages() if bool(self.state.metadata.get("failed")) else []
        )
        self.orchestrator._emit(
            "state.reconcile",
            run_id=self.state.run_id,
            source=f"state_action.{self.command}",
            missing_count=len(result.failing_services),
            missing_services=result.failing_services,
            requirement_issue_count=len(result.requirement_issues),
        )
        result.reconciled = True
        return result

    def _apply_selected_services(self, route: Route, selected_services: set[str]) -> None:
        assert self.state is not None
        filtered_state = self.orchestrator._filtered_state(self.state, selected_services)
        self.state = filtered_state
        self.orchestrator._emit(
            "state.selection.filtered",
            command=self.command,
            filtered_service_count=len(filtered_state.services),
        )

    def _selected_services_for_logs(self, route: Route) -> set[str] | None:
        selected_services = self._resolve_service_selection(route)
        if selected_services is not None:
            return selected_services

        if bool(route.flags.get("json")):
            assert self.state is not None
            return set(self.state.services.keys())
        if not self.orchestrator._interactive_selection_allowed(route):
            print(self.orchestrator._no_target_selected_message(route))
            return set()
        return None

    def _selected_services_for_clear_logs(self, route: Route) -> set[str]:
        assert self.state is not None
        selected_services = self._resolve_service_selection(
            route,
            prompt="Clear logs for",
            require_interactive_command=True,
        )
        return selected_services if selected_services is not None else set(self.state.services.keys())

    def _selected_services_for_errors(self, route: Route) -> set[str] | None:
        return self._resolve_service_selection(route, prompt="Errors for")

    def _resolve_service_selection(
        self,
        route: Route,
        *,
        prompt: str | None = None,
        require_interactive_command: bool = False,
    ) -> set[str] | None:
        assert self.state is not None
        selected_services = self.orchestrator._resolve_selected_services(route, self.state)
        self._emit_selection_filter(route, selected_services)
        if selected_services is not None:
            return selected_services
        if require_interactive_command and not bool(route.flags.get("interactive_command")):
            return None

        if prompt is None:
            selection = self.orchestrator._interactive_log_selection(route, self.state)
        else:
            selection = self.orchestrator._interactive_log_selection(route, self.state, prompt=prompt)
        if selection is not None and selection.cancelled:
            print(self.orchestrator._no_target_selected_message(route))
            return set()
        if selection is not None:
            return self.orchestrator._services_from_selection(selection, self.state)
        return None

    def _emit_selection_filter(self, route: Route, selected_services: set[str] | None) -> None:
        self.orchestrator._emit(
            "state.selection.filters",
            command=self.command,
            projects=list(route.projects),
            selected_service_count=(len(selected_services) if isinstance(selected_services, set) else None),
        )

    def _start_action(self) -> None:
        assert self.state is not None
        self.orchestrator._emit_state_action_start(command=self.command, state=self.state)

    def _run_logs(self, route: Route) -> int:
        assert self.state is not None
        selected_services = self._selected_services_for_logs(route)
        if selected_services is not None and not selected_services:
            if not bool(route.flags.get("interactive_command")):
                print("No matching targets found.")
            return 1
        if selected_services is not None:
            self._apply_selected_services(route, selected_services)

        self._start_action()
        tail = parse_int(str(route.flags.get("logs_tail", "20")), 20)
        follow = bool(route.flags.get("logs_follow"))
        duration_seconds = parse_float_or_none(route.flags.get("logs_duration"))
        if duration_seconds is not None and duration_seconds < 0:
            duration_seconds = 0.0
        no_color = bool(route.flags.get("logs_no_color")) or self.orchestrator._human_output_no_color(route)
        follower_pids = refresh_container_log_snapshots(
            self.runtime.raw_runtime,
            self.state,
            tail=max(tail, 0),
            follow=follow and not bool(route.flags.get("json")),
        )
        if bool(route.flags.get("json")):
            print(
                json.dumps(
                    self.orchestrator._logs_payload(
                        state=self.state,
                        tail=max(tail, 0),
                        follow=follow,
                        duration_seconds=duration_seconds,
                        no_color=True,
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
            return self._finish_action(0)
        try:
            with _interrupt_log_follow_on_termination(bool(follower_pids)):
                self.runtime.print_logs(
                    self.state,
                    tail=max(tail, 0),
                    follow=follow,
                    duration_seconds=duration_seconds,
                    no_color=no_color,
                )
        finally:
            stop_container_log_followers(self.runtime.raw_runtime, follower_pids)
        return self._finish_action(0)

    def _run_clear_logs(self, route: Route) -> int:
        assert self.state is not None
        selected_services = self._selected_services_for_clear_logs(route)
        if not selected_services:
            print("No matching targets found.")
            return 1
        self._apply_selected_services(route, selected_services)
        self._start_action()
        cleared, missing, unavailable, failed = self.orchestrator._clear_service_logs(
            self.state,
            quiet=bool(route.flags.get("json")),
            env=self.runtime.env,
            interactive_tty=RuntimeTerminalUI._can_interactive_tty(),
        )
        code = 1 if failed > 0 else 0
        if bool(route.flags.get("json")):
            print(
                json.dumps(
                    self.orchestrator._clear_logs_payload(
                        state=self.state,
                        cleared=cleared,
                        missing=missing,
                        unavailable=unavailable,
                        failed=failed,
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
            return self._finish_action(code)
        print(f"Log clear summary: cleared={cleared} missing={missing} unavailable={unavailable} failed={failed}")
        return self._finish_action(code)

    def _run_health(self, route: Route) -> int:
        assert self.state is not None
        self._start_action()
        reconciliation = self._ensure_reconciled()
        service_rows = self.orchestrator._health_service_rows(self.state)
        requirement_rows = self.orchestrator._requirement_health_rows(self.state)
        dependency_rows = requirement_rows or [
            {
                "project": issue["project"],
                "component": issue["component"],
                "status": issue["status"],
                "port": issue["port"],
            }
            for issue in reconciliation.requirement_issues
        ]
        total_projects = len(
            self.orchestrator._health_project_order(service_rows=service_rows, dependency_rows=dependency_rows)
        )
        status_counts = self.orchestrator._health_status_counts(
            service_rows=service_rows,
            dependency_rows=dependency_rows,
        )
        if bool(route.flags.get("json")):
            return self._print_health_json(
                route,
                service_rows=service_rows,
                dependency_rows=dependency_rows,
                status_counts=status_counts,
                total_projects=total_projects,
                reconciliation=reconciliation,
            )
        return self._print_health_text(
            route,
            service_rows=service_rows,
            dependency_rows=dependency_rows,
            status_counts=status_counts,
            total_projects=total_projects,
            reconciliation=reconciliation,
        )

    def _print_health_json(
        self,
        route: Route,
        *,
        service_rows: list[dict[str, object]],
        dependency_rows: list[dict[str, object]],
        status_counts: dict[str, int],
        total_projects: int,
        reconciliation: StateActionReconciliation,
    ) -> int:
        assert self.state is not None
        cwd_project, warnings = cwd_runtime_warnings(
            self.state,
            runtime=self.runtime.raw_runtime,
            requested_projects=route.projects,
        )
        self.orchestrator._emit_cwd_runtime_mismatch_warnings(command=self.command, state=self.state, warnings=warnings)
        diagnostics = build_runtime_diagnostics(
            self.state,
            env=self.runtime.env,
            config=self.runtime.config,
            runtime=self.runtime.raw_runtime,
        )
        diagnostic_warnings = diagnostics.get("warnings", [])
        if not isinstance(diagnostic_warnings, list):
            diagnostic_warnings = []
        combined_warnings = [*warnings, *diagnostic_warnings]
        print(
            json.dumps(
                self.orchestrator._health_payload(
                    state=self.state,
                    service_rows=service_rows,
                    dependency_rows=dependency_rows,
                    status_counts=status_counts,
                    recent_failures=reconciliation.recent_failures,
                    failing_services=reconciliation.failing_services,
                    requirement_issues=reconciliation.requirement_issues,
                    total_projects=total_projects,
                    strict=bool(route.flags.get("strict")),
                    cwd_project=cwd_project,
                    warnings=combined_warnings,
                    runtime_diagnostics=diagnostics,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return self._finish_action(self._health_exit_code(route, service_rows, dependency_rows, reconciliation))

    def _print_health_text(
        self,
        route: Route,
        *,
        service_rows: list[dict[str, object]],
        dependency_rows: list[dict[str, object]],
        status_counts: dict[str, int],
        total_projects: int,
        reconciliation: StateActionReconciliation,
    ) -> int:
        assert self.state is not None
        palette = self.orchestrator._health_palette()
        reset = palette["reset"]
        bold = palette["bold"]
        cyan = palette["cyan"]
        dim = palette["dim"]
        green = palette["green"]
        yellow = palette["yellow"]
        red = palette["red"]
        print(f"{bold}{cyan}Health Check{reset}")
        print(
            f"{dim}run_id: {self.state.run_id} mode: {self.state.mode} | "
            f"projects={total_projects} services={len(service_rows)} dependencies={len(dependency_rows)}{reset}"
        )
        _cwd_project, warnings = cwd_runtime_warnings(
            self.state,
            runtime=self.runtime.raw_runtime,
            requested_projects=route.projects,
        )
        for warning in warnings:
            print(f"{yellow}Warning: {warning['message']}{reset}")
        self.orchestrator._emit_cwd_runtime_mismatch_warnings(command=self.command, state=self.state, warnings=warnings)
        health_status = self._health_status(service_rows, dependency_rows, reconciliation)
        print(
            "status: "
            f"{green}healthy/running={status_counts['ok']}{reset} "
            f"{yellow}starting/simulated={status_counts['warn']}{reset} "
            f"{red}issues={status_counts['bad']}{reset}"
        )
        print(
            "summary: "
            f"critical_issues={len(cast(list[object], health_status['critical_failures']))} "
            f"optional_degraded={len(cast(list[object], health_status['optional_failures']))}"
        )
        self.orchestrator._print_health_rows(
            service_rows=service_rows,
            dependency_rows=dependency_rows,
            palette=palette,
        )
        if not service_rows and not dependency_rows:
            print("No services or dependencies tracked in current runtime state.")
        if (
            not reconciliation.failing_services
            and not reconciliation.requirement_issues
            and reconciliation.recent_failures
        ):
            for failure in reconciliation.recent_failures:
                print(failure)
        return self._finish_action(self._health_exit_code(route, service_rows, dependency_rows, reconciliation))

    def _health_exit_code(
        self,
        route: Route,
        service_rows: list[dict[str, object]],
        dependency_rows: list[dict[str, object]],
        reconciliation: StateActionReconciliation,
    ) -> int:
        health_status = self._health_status(service_rows, dependency_rows, reconciliation)
        strict_blocking = bool(route.flags.get("strict")) and bool(health_status["optional_failures"])
        return 0 if bool(health_status["ok"]) and not strict_blocking else 1

    def _health_status(
        self,
        service_rows: list[dict[str, object]],
        dependency_rows: list[dict[str, object]],
        reconciliation: StateActionReconciliation,
    ) -> dict[str, object]:
        return self.orchestrator._health_status_summary(
            service_rows=service_rows,
            dependency_rows=dependency_rows,
            failing_services=reconciliation.failing_services,
            requirement_issues=reconciliation.requirement_issues,
            recent_failures=reconciliation.recent_failures,
        )

    def _run_errors(self, route: Route) -> int:
        assert self.state is not None
        selected_services = self._selected_services_for_errors(route)
        if selected_services is not None and not selected_services:
            if not bool(route.flags.get("interactive_command")):
                print("No matching targets found.")
            return 1
        if selected_services is not None:
            self._apply_selected_services(route, selected_services)

        self._start_action()
        reconciliation = self._ensure_reconciled()
        failed = [
            svc for svc in self.state.services.values() if (svc.status or "").lower() not in {"running", "healthy"}
        ]
        log_issue_limit = max(
            parse_int(str(route.flags.get("logs_tail", DEFAULT_LOG_ISSUE_LIMIT)), DEFAULT_LOG_ISSUE_LIMIT),
            0,
        )
        refresh_container_log_snapshots(
            self.runtime.raw_runtime,
            self.state,
            tail=log_issue_limit,
            follow=False,
        )
        log_issues = self.orchestrator._service_log_issues(self.state, max_matches=log_issue_limit)
        has_errors = bool(failed or reconciliation.requirement_issues or reconciliation.recent_failures or log_issues)
        if bool(route.flags.get("json")):
            print(
                json.dumps(
                    self.orchestrator._errors_payload(
                        state=self.state,
                        failed_services=failed,
                        requirement_issues=reconciliation.requirement_issues,
                        recent_failures=reconciliation.recent_failures,
                        log_issues=log_issues,
                        selected_services=selected_services,
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
            return self._finish_action(1 if has_errors else 0)
        if not has_errors:
            print("No known service errors.")
            return self._finish_action(0)
        self._print_error_text(route, failed, reconciliation, log_issues)
        return self._finish_action(1)

    def _print_error_text(
        self,
        route: Route,
        failed: list[Any],
        reconciliation: StateActionReconciliation,
        log_issues: list[dict[str, object]],
    ) -> None:
        no_color = self.orchestrator._human_output_no_color(route)
        for service in failed:
            self.orchestrator._print_highlighted_line(f"{service.name}: status={service.status}", no_color=no_color)
        for issue in reconciliation.requirement_issues:
            if issue["port"] is not None:
                self.orchestrator._print_highlighted_line(
                    f"{issue['project']} {issue['component']}: status={issue['status']} port={issue['port']}",
                    no_color=no_color,
                )
            else:
                self.orchestrator._print_highlighted_line(
                    f"{issue['project']} {issue['component']}: status={issue['status']}",
                    no_color=no_color,
                )
        for log_issue in log_issues:
            log_path = str(log_issue.get("log_path") or "")
            suffix = f" ({log_path})" if log_path else ""
            self.orchestrator._print_highlighted_line(f"{log_issue['service']}: log issues{suffix}", no_color=no_color)
            lines = log_issue.get("lines", [])
            if not isinstance(lines, list):
                lines = []
            for line in lines:
                self.orchestrator._print_highlighted_line(f"  {line}", no_color=no_color)
        for failure in reconciliation.recent_failures:
            self.orchestrator._print_highlighted_line(failure, no_color=no_color)


def execute_state_action(orchestrator: Any, route: Route) -> int:
    return StateActionCommandRunner(orchestrator).execute(route)
