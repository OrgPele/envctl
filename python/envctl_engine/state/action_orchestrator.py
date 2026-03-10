from __future__ import annotations

from collections.abc import Callable
from collections.abc import Sequence
import concurrent.futures
import json
from pathlib import Path
import sys
from typing import Any

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.requirements.core import dependency_definitions
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


class StateActionOrchestrator:
    def __init__(self, runtime: Any) -> None:
        self.runtime = StateActionRuntimeFacade(runtime)

    def execute(self, route: Route) -> int:
        rt = self.runtime
        command = route.command
        state = rt.load_state(route)
        if state is None:
            print(f"No previous state found for '{command}'.")
            return 1
        current_state = state

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
            tail = parse_int(str(route.flags.get("logs_tail", "20")), 20)
            follow = bool(route.flags.get("logs_follow"))
            raw_duration = route.flags.get("logs_duration")
            duration_seconds = parse_float_or_none(raw_duration)
            if duration_seconds is not None and duration_seconds < 0:
                duration_seconds = 0.0
            no_color = bool(route.flags.get("logs_no_color")) or self._runtime_is_truthy(rt.env.get("NO_COLOR"))
            if bool(route.flags.get("json")):
                print(
                    json.dumps(
                        self._logs_payload(
                            state=current_state,
                            tail=max(tail, 0),
                            follow=follow,
                            duration_seconds=duration_seconds,
                            no_color=no_color,
                        ),
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 0
            rt.print_logs(
                current_state,
                tail=max(tail, 0),
                follow=follow,
                duration_seconds=duration_seconds,
                no_color=no_color,
            )
            return 0
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
            cleared, missing, unavailable, failed = self._clear_service_logs(
                current_state,
                quiet=bool(route.flags.get("json")),
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
                return 1 if failed > 0 else 0
            print(f"Log clear summary: cleared={cleared} missing={missing} unavailable={unavailable} failed={failed}")
            return 1 if failed > 0 else 0
        if command == "health":
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
                        ),
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 0 if not failing_services and not requirement_issues and not recent_failures else 1
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
            print(
                "status: "
                f"{green}healthy/running={status_counts['ok']}{reset} "
                f"{yellow}starting/simulated={status_counts['warn']}{reset} "
                f"{red}issues={status_counts['bad']}{reset}"
            )
            self._print_health_rows(service_rows=service_rows, dependency_rows=dependency_rows, palette=palette)

            if not service_rows and not dependency_rows:
                print("No services or dependencies tracked in current runtime state.")

            if not failing_services and not requirement_issues and recent_failures:
                for failure in recent_failures:
                    print(failure)
            return 0 if not failing_services and not requirement_issues and not recent_failures else 1
        if command == "errors":
            ensure_reconciled()
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
            failed = [
                svc
                for svc in current_state.services.values()
                if (svc.status or "").lower() not in {"running", "healthy"}
            ]
            if bool(route.flags.get("json")):
                print(
                    json.dumps(
                        self._errors_payload(
                            state=current_state,
                            failed_services=failed,
                            requirement_issues=requirement_issues,
                            recent_failures=recent_failures,
                            selected_services=selected_services,
                        ),
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 0 if not failed and not requirement_issues and not recent_failures else 1
            if not failed and not requirement_issues and not recent_failures:
                print("No known service errors.")
                return 0
            for service in failed:
                print(f"{service.name}: status={service.status}")
            for issue in requirement_issues:
                if issue["port"] is not None:
                    print(f"{issue['project']} {issue['component']}: status={issue['status']} port={issue['port']}")
                else:
                    print(f"{issue['project']} {issue['component']}: status={issue['status']}")
            for failure in recent_failures:
                print(failure)
            return 1

        return rt.unsupported_command(command)

    def _health_payload(
        self,
        *,
        state: RunState,
        service_rows: list[dict[str, object]],
        dependency_rows: list[dict[str, object]],
        status_counts: dict[str, int],
        recent_failures: list[str],
        failing_services: list[str],
        requirement_issues: list[dict[str, object]],
        total_projects: int,
    ) -> dict[str, object]:
        return {
            "run_id": state.run_id,
            "mode": state.mode,
            "projects": total_projects,
            "services": service_rows,
            "dependencies": dependency_rows,
            "status_counts": status_counts,
            "healthy": not failing_services and not requirement_issues and not recent_failures,
            "issues": {
                "failing_services": list(failing_services),
                "requirement_issues": requirement_issues,
                "recent_failures": list(recent_failures),
            },
        }

    def _errors_payload(
        self,
        *,
        state: RunState,
        failed_services: Sequence[ServiceRecord],
        requirement_issues: list[dict[str, object]],
        recent_failures: list[str],
        selected_services: set[str] | None,
    ) -> dict[str, object]:
        return {
            "run_id": state.run_id,
            "mode": state.mode,
            "selected_services": sorted(selected_services) if isinstance(selected_services, set) else None,
            "failed_services": self._parallel_service_map(list(failed_services), self._failed_service_payload),
            "requirement_issues": requirement_issues,
            "recent_failures": list(recent_failures),
            "ok": not failed_services and not requirement_issues and not recent_failures,
        }

    def _logs_payload(
        self,
        *,
        state: RunState,
        tail: int,
        follow: bool,
        duration_seconds: float | None,
        no_color: bool,
    ) -> dict[str, object]:
        snapshots = self._parallel_service_map(
            list(state.services.values()),
            lambda service: self._log_snapshot(service, tail=tail, no_color=no_color),
        )
        return {
            "run_id": state.run_id,
            "mode": state.mode,
            "tail": tail,
            "follow_requested": follow,
            "duration_seconds": duration_seconds,
            "streaming": False,
            "services": snapshots,
        }

    def _clear_logs_payload(
        self,
        *,
        state: RunState,
        cleared: int,
        missing: int,
        unavailable: int,
        failed: int,
    ) -> dict[str, object]:
        snapshots = self._parallel_service_map(
            list(state.services.values()),
            self._clear_log_snapshot,
        )
        return {
            "run_id": state.run_id,
            "mode": state.mode,
            "summary": {
                "cleared": cleared,
                "missing": missing,
                "unavailable": unavailable,
                "failed": failed,
            },
            "services": snapshots,
            "ok": failed == 0,
        }

    def _log_snapshot(self, service: object, *, tail: int, no_color: bool) -> dict[str, object]:
        log_path_raw = str(getattr(service, "log_path", "") or "").strip()
        payload: dict[str, object] = {
            "name": str(getattr(service, "name", "")),
            "status": str(getattr(service, "status", "") or "unknown"),
            "log_path": log_path_raw or None,
            "exists": False,
            "tail_lines": [],
        }
        if not log_path_raw:
            payload["reason"] = "unavailable"
            return payload
        log_path = Path(log_path_raw)
        if not log_path.is_file():
            payload["reason"] = "missing"
            return payload
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        payload["exists"] = True
        payload["size_bytes"] = log_path.stat().st_size
        payload["tail_lines"] = [self.runtime.normalize_log_line(line, no_color=no_color) for line in lines[-tail:]]
        return payload

    def _clear_log_snapshot(self, service: object) -> dict[str, object]:
        log_path_raw = str(getattr(service, "log_path", "") or "").strip()
        payload: dict[str, object] = {
            "name": str(getattr(service, "name", "")),
            "log_path": log_path_raw or None,
            "status": "unknown",
        }
        if not log_path_raw:
            payload["status"] = "unavailable"
            return payload
        log_path = Path(log_path_raw)
        if not log_path.is_file():
            payload["status"] = "missing"
            return payload
        payload["status"] = "cleared"
        return payload

    @staticmethod
    def _failed_service_payload(service: object) -> dict[str, object]:
        return {
            "name": str(getattr(service, "name", "")),
            "status": str(getattr(service, "status", "") or "unknown"),
            "log_path": str(getattr(service, "log_path", "") or "") or None,
        }

    def _emit(self, event: str, **payload: object) -> None:
        self.runtime.emit(event, **payload)

    def _runtime_is_truthy(self, value: object) -> bool:
        return self.runtime.is_truthy(value)

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
                target = str(raw).strip().lower()
                if not target:
                    continue
                for name in state.services:
                    if name.lower() == target:
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

    def _requirement_health_rows(self, state: RunState) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        component_order = {definition.id: index for index, definition in enumerate(dependency_definitions())}
        for project, requirements in state.requirements.items():
            for definition in dependency_definitions():
                component = definition.id
                data = requirements.component(component)
                if not bool(data.get("enabled", False)):
                    continue
                status = str(data.get("runtime_status", "")).strip().lower()
                if not status:
                    if bool(data.get("simulated", False)):
                        status = "simulated"
                    elif bool(data.get("success", False)):
                        status = "healthy"
                    else:
                        status = "unknown"
                raw_port = data.get("final") or data.get("requested")
                port = raw_port if isinstance(raw_port, int) and raw_port > 0 else None
                rows.append(
                    {
                        "project": project,
                        "component": component,
                        "status": status,
                        "port": port,
                    }
                )
        rows.sort(key=lambda row: (str(row["project"]).lower(), component_order.get(str(row["component"]), 99)))
        return rows

    def _health_service_rows(self, state: RunState) -> list[dict[str, object]]:
        def _service_row(service: ServiceRecord) -> dict[str, object]:
            return {
                "project": self.runtime.project_name_from_service(service.name) or "unknown",
                "name": service.name,
                "status": str(service.status or "unknown").strip().lower() or "unknown",
                "port": service.actual_port if service.actual_port is not None else service.requested_port,
            }

        rows = self._parallel_service_map(
            list(state.services.values()),
            _service_row,
        )
        rows.sort(key=lambda row: (str(row["project"]).lower(), str(row["name"]).lower()))
        return rows

    @staticmethod
    def _health_project_order(
        *,
        service_rows: list[dict[str, object]],
        dependency_rows: list[dict[str, object]],
    ) -> list[str]:
        order: list[str] = []
        seen: set[str] = set()
        for row in [*service_rows, *dependency_rows]:
            project = str(row.get("project", "")).strip() or "unknown"
            lowered = project.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            order.append(project)
        return order

    def _print_health_rows(
        self,
        *,
        service_rows: list[dict[str, object]],
        dependency_rows: list[dict[str, object]],
        palette: dict[str, str],
    ) -> None:
        reset = palette["reset"]
        bold = palette["bold"]
        blue = palette["blue"]
        magenta = palette["magenta"]
        dim = palette["dim"]
        project_order = self._health_project_order(service_rows=service_rows, dependency_rows=dependency_rows)
        for project in project_order:
            print(f"\n{bold}{blue}{project}{reset}")
            project_services = [
                row for row in service_rows if str(row.get("project", "")).strip().lower() == project.lower()
            ]
            project_dependencies = [
                row for row in dependency_rows if str(row.get("project", "")).strip().lower() == project.lower()
            ]
            if project_services:
                print(f"  {magenta}Services ({len(project_services)}){reset}")
                for row in project_services:
                    status = str(row.get("status", "unknown"))
                    icon = self._health_status_icon(status)
                    icon_color = self._health_status_color(status, palette)
                    service_name = str(row.get("name", "service"))
                    display_name = self._health_service_display_name(project=project, service_name=service_name)
                    port_raw = row.get("port")
                    port_text = str(port_raw) if port_raw is not None else "n/a"
                    print(
                        f"    {icon_color}{icon}{reset} {display_name:<12} "
                        f"{dim}status={status:<10} port={port_text}{reset}"
                    )
            if project_dependencies:
                print(f"  {magenta}Dependencies ({len(project_dependencies)}){reset}")
                for row in project_dependencies:
                    status = str(row.get("status", "unknown"))
                    icon = self._health_status_icon(status)
                    icon_color = self._health_status_color(status, palette)
                    port_text = row.get("port") if row.get("port") is not None else "n/a"
                    component = str(row.get("component", "dependency"))
                    print(
                        f"    {icon_color}{icon}{reset} {component:<12} "
                        f"{dim}status={status:<10} port={port_text}{reset}"
                    )

    @staticmethod
    def _health_service_display_name(*, project: str, service_name: str) -> str:
        project_prefix = f"{project} "
        if service_name.startswith(project_prefix):
            trimmed = service_name[len(project_prefix) :].strip()
            if trimmed:
                return trimmed
        return service_name

    @classmethod
    def _health_status_counts(
        cls,
        *,
        service_rows: list[dict[str, object]],
        dependency_rows: list[dict[str, object]],
    ) -> dict[str, int]:
        counters = {"ok": 0, "warn": 0, "bad": 0}
        for row in [*service_rows, *dependency_rows]:
            status = str(row.get("status", "unknown"))
            icon = cls._health_status_icon(status)
            if icon == "✓":
                counters["ok"] += 1
            elif icon == "~":
                counters["warn"] += 1
            else:
                counters["bad"] += 1
        return counters

    @staticmethod
    def _health_status_icon(status: str) -> str:
        lowered = str(status).strip().lower()
        if lowered in {"running", "healthy"}:
            return "✓"
        if lowered in {"simulated", "starting", "unknown"}:
            return "~"
        return "!"

    @staticmethod
    def _health_status_color(status: str, palette: dict[str, str]) -> str:
        lowered = str(status).strip().lower()
        if lowered in {"running", "healthy"}:
            return palette["green"]
        if lowered in {"simulated", "starting", "unknown"}:
            return palette["yellow"]
        return palette["red"]

    def _health_palette(self) -> dict[str, str]:
        env = getattr(self.runtime, "env", {})
        interactive_tty = RuntimeTerminalUI._can_interactive_tty()
        enabled = colors_enabled(env, stream=sys.stdout, interactive_tty=interactive_tty)
        if not enabled:
            return {
                "reset": "",
                "bold": "",
                "dim": "",
                "cyan": "",
                "blue": "",
                "magenta": "",
                "green": "",
                "yellow": "",
                "red": "",
            }
        return {
            "reset": "\033[0m",
            "bold": "\033[1m",
            "dim": "\033[2m",
            "cyan": "\033[36m",
            "blue": "\033[34m",
            "magenta": "\033[35m",
            "green": "\033[32m",
            "yellow": "\033[33m",
            "red": "\033[31m",
        }

    def _no_target_selected_message(self, route: Route) -> str:
        interactive_allowed = self._interactive_selection_allowed(route)
        return no_target_selected_message(route.command, route=route, interactive_allowed=interactive_allowed)

    @staticmethod
    def _clear_service_logs(state: RunState, *, quiet: bool = False) -> tuple[int, int, int, int]:
        def clear_one(service: ServiceRecord) -> tuple[int, int, int, int, str | None]:
            raw_path = str(getattr(service, "log_path", "") or "").strip()
            if not raw_path:
                return 0, 0, 1, 0, (None if quiet else f"{service.name}: log=n/a")
            log_path = Path(raw_path)
            if not log_path.is_file():
                return 0, 1, 0, 0, (None if quiet else f"{service.name}: log missing at {log_path}")
            try:
                with log_path.open("w", encoding="utf-8"):
                    pass
                return 1, 0, 0, 0, (None if quiet else f"{service.name}: log cleared at {log_path}")
            except OSError as exc:
                return 0, 0, 0, 1, (None if quiet else f"{service.name}: failed to clear log at {log_path} ({exc})")

        cleared = 0
        missing = 0
        unavailable = 0
        failed = 0
        services = list(state.services.values())
        worker_count = min(max(len(services), 1), 8)
        if worker_count <= 1:
            results = [clear_one(service) for service in services]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
                results = list(pool.map(clear_one, services))
        for cleared_one, missing_one, unavailable_one, failed_one, line in results:
            cleared += cleared_one
            missing += missing_one
            unavailable += unavailable_one
            failed += failed_one
            if line:
                print(line)
        return cleared, missing, unavailable, failed

    @staticmethod
    def _parallel_service_map(
        services: Sequence[ServiceRecord], fn: Callable[[ServiceRecord], dict[str, object]]
    ) -> list[dict[str, object]]:
        if len(services) <= 1:
            return [fn(service) for service in services]
        worker_count = min(len(services), 8)
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
            return list(pool.map(fn, services))
