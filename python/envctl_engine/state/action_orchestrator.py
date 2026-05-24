from __future__ import annotations

from collections.abc import Callable
import json
import sys
from typing import Any

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.browser_diagnostics import build_runtime_diagnostics
from envctl_engine.state.models import RunState
from envctl_engine.state.action_health_support import StateActionHealthSupport
from envctl_engine.state.action_log_support import DEFAULT_LOG_ISSUE_LIMIT, StateActionLogSupport
from envctl_engine.shared.parsing import parse_bool, parse_float_or_none, parse_int
from envctl_engine.ui.color_policy import colors_enabled
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI
from envctl_engine.ui.selection_support import (
    interactive_selection_allowed,
    no_target_selected_message,
    project_names_from_state,
    services_from_selection,
)
from envctl_engine.ui.selection_types import TargetSelection
from envctl_engine.shared.services import service_matches_selector
from envctl_engine.state.project_runtime import (
    cwd_runtime_warnings,
    project_resolution_event_payload,
    resolve_requested_project_state,
)


class StateActionRuntimeFacade:
    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self.env = getattr(runtime, "env", {})
        self.config = getattr(runtime, "config", None)

    def _resolve_callable(self, *names: str) -> Callable[..., object]:
        for name in names:
            candidate = getattr(self._runtime, name, None)
            if callable(candidate):
                return candidate
        joined = ", ".join(names)
        raise AttributeError(f"{type(self._runtime).__name__} is missing required state collaborator ({joined})")

    def load_state(self, route: Route) -> RunState | None:
        load_state = getattr(self._runtime, "load_state", None)
        if callable(load_state):
            return load_state(route)
        strict_lookup = self._resolve_callable("_state_lookup_strict_mode_match")
        legacy_load = self._resolve_callable("_try_load_existing_state")
        return legacy_load(
            mode=route.mode,
            strict_mode_match=bool(strict_lookup(route)),
        )

    def reconcile_state_truth(self, state: RunState) -> list[str]:
        reconcile = self._resolve_callable("reconcile_state_truth", "_reconcile_state_truth")
        return reconcile(state)

    def requirement_truth_issues(self, state: RunState) -> list[dict[str, object]]:
        requirement_issues = self._resolve_callable("requirement_truth_issues", "_requirement_truth_issues")
        return requirement_issues(state)

    def recent_failure_messages(self) -> list[str]:
        recent_failures = self._resolve_callable("recent_failure_messages", "_recent_failure_messages")
        return recent_failures()

    def print_logs(
        self,
        state: RunState,
        *,
        tail: int,
        follow: bool,
        duration_seconds: float | None,
        no_color: bool,
    ) -> None:
        print_logs = self._resolve_callable("print_logs", "_print_logs")
        print_logs(
            state,
            tail=tail,
            follow=follow,
            duration_seconds=duration_seconds,
            no_color=no_color,
        )

    def unsupported_command(self, command: str) -> int:
        unsupported = self._resolve_callable("unsupported_command", "_unsupported_command")
        return int(unsupported(command))

    def emit(self, event: str, **payload: object) -> None:
        candidate = getattr(self._runtime, "_emit", None)
        if callable(candidate):
            emitter: Callable[..., object] = candidate
            emitter(event, **payload)

    def is_truthy(self, value: object) -> bool:
        candidate = getattr(self._runtime, "_is_truthy", None)
        if callable(candidate):
            checker: Callable[[object], object] = candidate
            return bool(checker(value))
        return parse_bool(value, False)

    def select_grouped_targets(self, **kwargs: object) -> TargetSelection:
        select = self._resolve_callable("select_grouped_targets", "_select_grouped_targets")
        return select(**kwargs)

    def selectors_from_passthrough(self, passthrough_args: list[str]) -> set[str]:
        selectors = self._resolve_callable("selectors_from_passthrough", "_selectors_from_passthrough")
        return selectors(passthrough_args)

    def project_name_from_service(self, service_name: str) -> str:
        project_name = self._resolve_callable("project_name_from_service", "_project_name_from_service")
        return str(project_name(service_name))

    def normalize_log_line(self, line: str, *, no_color: bool) -> str:
        candidate = getattr(self._runtime, "_normalize_log_line", None)
        if callable(candidate):
            return str(candidate(line, no_color=no_color))
        return line

    @property
    def raw_runtime(self) -> Any:
        return self._runtime


class StateActionOrchestrator(StateActionLogSupport, StateActionHealthSupport):
    def __init__(self, runtime: Any) -> None:
        self.runtime = StateActionRuntimeFacade(runtime)
        super().__init__(
            normalize_log_line=lambda line, no_color: self.runtime.normalize_log_line(line, no_color=no_color),
        )

    def execute(self, route: Route) -> int:
        rt = self.runtime
        command = route.command
        state = rt.load_state(route)
        if state is None:
            print(f"No previous state found for '{command}'.")
            return 1
        current_state = state
        if route.projects:
            resolution = resolve_requested_project_state(
                current_state,
                route.projects,
                command=command,
                runtime=rt.raw_runtime,
            )
            if not resolution.ok:
                self._emit(
                    "state.project_resolution.failed",
                    **project_resolution_event_payload(resolution, current_state, runtime=rt.raw_runtime),
                )
                if bool(route.flags.get("json")):
                    print(json.dumps(resolution.payload(), indent=2, sort_keys=True))
                else:
                    print(self._project_mismatch_message(resolution.payload()))
                return 1
            self._emit(
                "state.project_resolution.ok",
                **project_resolution_event_payload(resolution, current_state, runtime=rt.raw_runtime),
            )
            if not bool(route.flags.get("all")) and resolution.state is not None:
                current_state = resolution.state

        def finish_action(code: int, action_state: RunState = current_state) -> int:
            self._emit_state_action_finish(command=command, state=action_state, code=code)
            return code

        failing_services: list[str] = []
        requirement_issues: list[dict[str, object]] = []
        recent_failures: list[str] = []
        reconciled = False

        def ensure_reconciled() -> None:
            nonlocal failing_services, requirement_issues, recent_failures, reconciled
            if reconciled:
                return
            failing_services = rt.reconcile_state_truth(current_state)
            requirement_issues = rt.requirement_truth_issues(current_state)
            recent_failures = rt.recent_failure_messages() if bool(current_state.metadata.get("failed")) else []
            self._emit(
                "state.reconcile",
                run_id=current_state.run_id,
                source=f"state_action.{command}",
                missing_count=len(failing_services),
                missing_services=failing_services,
                requirement_issue_count=len(requirement_issues),
            )
            reconciled = True

        if command == "logs":
            selected_services = self._resolve_selected_services(route, current_state)
            self._emit(
                "state.selection.filters",
                command=command,
                projects=list(route.projects),
                selected_service_count=(len(selected_services) if isinstance(selected_services, set) else None),
            )
            if selected_services is None:
                selection = self._interactive_log_selection(route, current_state)
                if selection is not None and selection.cancelled:
                    print(self._no_target_selected_message(route))
                    return 1
                if selection is not None:
                    selected_services = self._services_from_selection(selection, current_state)
                elif bool(route.flags.get("json")):
                    selected_services = set(current_state.services.keys())
                elif not self._interactive_selection_allowed(route):
                    print(self._no_target_selected_message(route))
                    return 1
            if selected_services is not None and not selected_services:
                print("No matching targets found.")
                return 1
            if selected_services is not None:
                current_state = self._filtered_state(current_state, selected_services)
                self._emit(
                    "state.selection.filtered",
                    command=command,
                    filtered_service_count=len(current_state.services),
                )
            self._emit_state_action_start(command=command, state=current_state)
            tail = parse_int(str(route.flags.get("logs_tail", "20")), 20)
            follow = bool(route.flags.get("logs_follow"))
            raw_duration = route.flags.get("logs_duration")
            duration_seconds = parse_float_or_none(raw_duration)
            if duration_seconds is not None and duration_seconds < 0:
                duration_seconds = 0.0
            no_color = bool(route.flags.get("logs_no_color")) or self._human_output_no_color(route)
            if bool(route.flags.get("json")):
                print(
                    json.dumps(
                        self._logs_payload(
                            state=current_state,
                            tail=max(tail, 0),
                            follow=follow,
                            duration_seconds=duration_seconds,
                            no_color=True,
                        ),
                        indent=2,
                        sort_keys=True,
                    )
                )
                return finish_action(0, current_state)
            rt.print_logs(
                current_state,
                tail=max(tail, 0),
                follow=follow,
                duration_seconds=duration_seconds,
                no_color=no_color,
            )
            return finish_action(0, current_state)
        if command == "clear-logs":
            selected_services = self._resolve_selected_services(route, current_state)
            self._emit(
                "state.selection.filters",
                command=command,
                projects=list(route.projects),
                selected_service_count=(len(selected_services) if isinstance(selected_services, set) else None),
            )
            if selected_services is None and bool(route.flags.get("interactive_command")):
                selection = self._interactive_log_selection(route, current_state, prompt="Clear logs for")
                if selection is not None and selection.cancelled:
                    print(self._no_target_selected_message(route))
                    return 1
                if selection is not None:
                    selected_services = self._services_from_selection(selection, current_state)
            if selected_services is None:
                selected_services = set(current_state.services.keys())
            if not selected_services:
                print("No matching targets found.")
                return 1
            current_state = self._filtered_state(current_state, selected_services)
            self._emit(
                "state.selection.filtered",
                command=command,
                filtered_service_count=len(current_state.services),
            )
            self._emit_state_action_start(command=command, state=current_state)
            cleared, missing, unavailable, failed = self._clear_service_logs(
                current_state,
                quiet=bool(route.flags.get("json")),
                env=rt.env,
                interactive_tty=RuntimeTerminalUI._can_interactive_tty(),
            )
            if bool(route.flags.get("json")):
                print(
                    json.dumps(
                        self._clear_logs_payload(
                            state=current_state,
                            cleared=cleared,
                            missing=missing,
                            unavailable=unavailable,
                            failed=failed,
                        ),
                        indent=2,
                        sort_keys=True,
                    )
                )
                return finish_action(1 if failed > 0 else 0, current_state)
            print(f"Log clear summary: cleared={cleared} missing={missing} unavailable={unavailable} failed={failed}")
            return finish_action(1 if failed > 0 else 0, current_state)
        if command == "health":
            self._emit_state_action_start(command=command, state=current_state)
            ensure_reconciled()
            service_rows = self._health_service_rows(current_state)
            requirement_rows = self._requirement_health_rows(current_state)
            dependency_rows = requirement_rows
            if not dependency_rows:
                dependency_rows = [
                    {
                        "project": issue["project"],
                        "component": issue["component"],
                        "status": issue["status"],
                        "port": issue["port"],
                    }
                    for issue in requirement_issues
                ]

            total_projects = len(self._health_project_order(service_rows=service_rows, dependency_rows=dependency_rows))
            status_counts = self._health_status_counts(service_rows=service_rows, dependency_rows=dependency_rows)
            if bool(route.flags.get("json")):
                cwd_project, warnings = cwd_runtime_warnings(
                    current_state,
                    runtime=rt.raw_runtime,
                    requested_projects=route.projects,
                )
                self._emit_cwd_runtime_mismatch_warnings(command=command, state=current_state, warnings=warnings)
                diagnostics = build_runtime_diagnostics(
                    current_state,
                    env=rt.env,
                    config=rt.config,
                    runtime=rt.raw_runtime,
                )
                combined_warnings = [*warnings, *list(diagnostics.get("warnings", []))]
                print(
                    json.dumps(
                        self._health_payload(
                            state=current_state,
                            service_rows=service_rows,
                            dependency_rows=dependency_rows,
                            status_counts=status_counts,
                            recent_failures=recent_failures,
                            failing_services=failing_services,
                            requirement_issues=requirement_issues,
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
                health_status = self._health_status_summary(
                    service_rows=service_rows,
                    dependency_rows=dependency_rows,
                    failing_services=failing_services,
                    requirement_issues=requirement_issues,
                    recent_failures=recent_failures,
                )
                strict_blocking = bool(route.flags.get("strict")) and bool(health_status["optional_failures"])
                return finish_action(0 if bool(health_status["ok"]) and not strict_blocking else 1, current_state)
            palette = self._health_palette()
            reset = palette["reset"]
            bold = palette["bold"]
            cyan = palette["cyan"]
            dim = palette["dim"]
            green = palette["green"]
            yellow = palette["yellow"]
            red = palette["red"]
            print(f"{bold}{cyan}Health Check{reset}")
            print(
                f"{dim}run_id: {current_state.run_id} mode: {current_state.mode} | "
                f"projects={total_projects} services={len(service_rows)} dependencies={len(dependency_rows)}{reset}"
            )
            _cwd_project, warnings = cwd_runtime_warnings(
                current_state,
                runtime=rt.raw_runtime,
                requested_projects=route.projects,
            )
            for warning in warnings:
                print(f"{yellow}Warning: {warning['message']}{reset}")
            self._emit_cwd_runtime_mismatch_warnings(command=command, state=current_state, warnings=warnings)
            health_status = self._health_status_summary(
                service_rows=service_rows,
                dependency_rows=dependency_rows,
                failing_services=failing_services,
                requirement_issues=requirement_issues,
                recent_failures=recent_failures,
            )
            print(
                "status: "
                f"{green}healthy/running={status_counts['ok']}{reset} "
                f"{yellow}starting/simulated={status_counts['warn']}{reset} "
                f"{red}issues={status_counts['bad']}{reset}"
            )
            print(
                "summary: "
                f"critical_issues={len(health_status['critical_failures'])} "
                f"optional_degraded={len(health_status['optional_failures'])}"
            )
            self._print_health_rows(service_rows=service_rows, dependency_rows=dependency_rows, palette=palette)

            if not service_rows and not dependency_rows:
                print("No services or dependencies tracked in current runtime state.")

            if not failing_services and not requirement_issues and recent_failures:
                for failure in recent_failures:
                    print(failure)
            strict_blocking = bool(route.flags.get("strict")) and bool(health_status["optional_failures"])
            return finish_action(0 if bool(health_status["ok"]) and not strict_blocking else 1, current_state)
        if command == "errors":
            selected_services = self._resolve_selected_services(route, current_state)
            self._emit(
                "state.selection.filters",
                command=command,
                projects=list(route.projects),
                selected_service_count=(len(selected_services) if isinstance(selected_services, set) else None),
            )
            if selected_services is None:
                selection = self._interactive_log_selection(route, current_state, prompt="Errors for")
                if selection is not None and selection.cancelled:
                    print(self._no_target_selected_message(route))
                    return 1
                if selection is not None:
                    selected_services = self._services_from_selection(selection, current_state)
            if selected_services is not None and not selected_services:
                print("No matching targets found.")
                return 1
            if selected_services is not None:
                current_state = self._filtered_state(current_state, selected_services)
                self._emit(
                    "state.selection.filtered",
                    command=command,
                    filtered_service_count=len(current_state.services),
                )
            self._emit_state_action_start(command=command, state=current_state)
            ensure_reconciled()
            failed = [
                svc
                for svc in current_state.services.values()
                if (svc.status or "").lower() not in {"running", "healthy"}
            ]
            log_issue_limit = max(
                parse_int(str(route.flags.get("logs_tail", DEFAULT_LOG_ISSUE_LIMIT)), DEFAULT_LOG_ISSUE_LIMIT),
                0,
            )
            log_issues = self._service_log_issues(current_state, max_matches=log_issue_limit)
            if bool(route.flags.get("json")):
                print(
                    json.dumps(
                        self._errors_payload(
                            state=current_state,
                            failed_services=failed,
                            requirement_issues=requirement_issues,
                            recent_failures=recent_failures,
                            log_issues=log_issues,
                            selected_services=selected_services,
                        ),
                        indent=2,
                        sort_keys=True,
                    )
                )
                return finish_action(
                    0 if not failed and not requirement_issues and not recent_failures and not log_issues else 1,
                    current_state,
                )
            if not failed and not requirement_issues and not recent_failures and not log_issues:
                print("No known service errors.")
                return finish_action(0, current_state)
            no_color = self._human_output_no_color(route)
            for service in failed:
                self._print_highlighted_line(f"{service.name}: status={service.status}", no_color=no_color)
            for issue in requirement_issues:
                if issue["port"] is not None:
                    self._print_highlighted_line(
                        f"{issue['project']} {issue['component']}: status={issue['status']} port={issue['port']}",
                        no_color=no_color,
                    )
                else:
                    self._print_highlighted_line(
                        f"{issue['project']} {issue['component']}: status={issue['status']}",
                        no_color=no_color,
                    )
            for log_issue in log_issues:
                log_path = str(log_issue.get("log_path") or "")
                suffix = f" ({log_path})" if log_path else ""
                self._print_highlighted_line(f"{log_issue['service']}: log issues{suffix}", no_color=no_color)
                for line in log_issue.get("lines", []):
                    self._print_highlighted_line(f"  {line}", no_color=no_color)
            for failure in recent_failures:
                self._print_highlighted_line(failure, no_color=no_color)
            return finish_action(1, current_state)

        return rt.unsupported_command(command)


    def _emit_cwd_runtime_mismatch_warnings(
        self,
        *,
        command: str,
        state: RunState,
        warnings: list[dict[str, object]],
    ) -> None:
        for warning in warnings:
            if str(warning.get("code") or "") != "cwd_runtime_mismatch":
                continue
            self._emit(
                "state.cwd_runtime_mismatch",
                run_id=state.run_id,
                mode=state.mode,
                command=command,
                cwd_project=warning.get("cwd_project"),
                active_projects=warning.get("active_projects"),
            )

    def _emit(self, event: str, **payload: object) -> None:
        self.runtime.emit(event, **payload)

    def _emit_state_action_start(self, *, command: str, state: RunState) -> None:
        self._emit(
            "state.action.start",
            command=command,
            run_id=state.run_id,
            mode=state.mode,
            service_count=len(state.services),
            dependency_count=len(state.requirements),
        )

    def _emit_state_action_finish(self, *, command: str, state: RunState, code: int) -> None:
        self._emit(
            "state.action.finish",
            command=command,
            run_id=state.run_id,
            mode=state.mode,
            code=code,
        )

    def _runtime_is_truthy(self, value: object) -> bool:
        return self.runtime.is_truthy(value)

    def _human_output_no_color(self, route: Route) -> bool:
        if self._runtime_is_truthy(self.runtime.env.get("NO_COLOR")):
            return True
        return not colors_enabled(
            self.runtime.env,
            stream=sys.stdout,
            interactive_tty=bool(route.flags.get("interactive_command")),
        )

    def _print_highlighted_line(self, line: str, *, no_color: bool) -> None:
        print(self.runtime.normalize_log_line(line, no_color=no_color))

    def _interactive_log_selection(
        self,
        route: Route,
        state: RunState,
        *,
        prompt: str = "Tail logs for",
    ) -> TargetSelection | None:
        if not self._interactive_selection_allowed(route):
            return None
        projects = self._project_names_from_state(state)
        services = sorted(state.services.keys())
        return self.runtime.select_grouped_targets(
            prompt=prompt,
            projects=projects,
            services=services,
            allow_all=True,
            multi=True,
        )

    def _interactive_selection_allowed(self, route: Route) -> bool:
        return interactive_selection_allowed(self.runtime.raw_runtime, route)

    def _resolve_selected_services(self, route: Route, state: RunState) -> set[str] | None:
        if bool(route.flags.get("all")):
            return set(state.services.keys())
        services_flag = route.flags.get("services")
        project_filters = {name.lower() for name in route.projects}
        project_filters.update(self.runtime.selectors_from_passthrough(route.passthrough_args))
        selected: set[str] = set()

        if isinstance(services_flag, list):
            for raw in services_flag:
                target = str(raw).strip()
                if not target:
                    continue
                for name, service in state.services.items():
                    if service_matches_selector(service, target):
                        selected.add(name)
        if project_filters:
            for name in state.services:
                project = self.runtime.project_name_from_service(name).lower()
                if project and project in project_filters:
                    selected.add(name)

        if selected:
            return selected
        if project_filters or (isinstance(services_flag, list) and services_flag):
            return set()
        return None

    def _project_names_from_state(self, state: RunState) -> list[object]:
        return project_names_from_state(self.runtime.raw_runtime, state)

    def _services_from_selection(self, selection: TargetSelection, state: RunState) -> set[str]:
        return services_from_selection(self.runtime.raw_runtime, selection, state)

    def _filtered_state(self, state: RunState, selected_services: set[str]) -> RunState:
        if not selected_services:
            return RunState(run_id=state.run_id, mode=state.mode)
        services = {name: svc for name, svc in state.services.items() if name in selected_services}
        project_names = {self.runtime.project_name_from_service(name) for name in services}
        requirements = {project: req for project, req in state.requirements.items() if project in project_names}
        return RunState(
            run_id=state.run_id,
            mode=state.mode,
            schema_version=state.schema_version,
            backend_mode=state.backend_mode,
            services=services,
            requirements=requirements,
            pointers=dict(state.pointers),
            metadata=dict(state.metadata),
        )

    def _no_target_selected_message(self, route: Route) -> str:
        interactive_allowed = self._interactive_selection_allowed(route)
        return no_target_selected_message(route.command, route=route, interactive_allowed=interactive_allowed)

    @staticmethod
    def _project_mismatch_message(payload: dict[str, object]) -> str:
        requested = payload.get("requested_project") or payload.get("requested_projects") or "unknown"
        active = payload.get("active_projects") or []
        return (
            f"Requested project is not running: {requested}\n"
            f"Active runtime projects: {', '.join(str(item) for item in active) or 'none'}"
        )
