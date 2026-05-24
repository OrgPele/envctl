from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence, cast

from envctl_engine.runtime.lifecycle_blast_support import LifecycleBlastCleanupSupport
from envctl_engine.runtime.engine_runtime_lifecycle_support import release_requirement_ports
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.shared.services import service_matches_selector, service_project_name, service_slug_from_record
from envctl_engine.ui.selection_support import (
    interactive_selection_allowed,
    project_names_from_state,
    services_from_selection,
)
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI  # noqa: F401
from envctl_engine.ui.selection_types import TargetSelection
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy
from envctl_engine.requirements.core import dependency_definitions


class _StateRepositoryProtocol(Protocol):
    def save_selected_stop_state(
        self,
        *,
        state: RunState,
        emit: Callable[..., None],
        runtime_map_builder: Callable[[RunState], dict[str, object]],
    ) -> dict[str, object]: ...

    def purge(self, *, aggressive: bool = False) -> None: ...


class _ProcessRuntimeProtocol(Protocol):
    def run(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> object: ...


class LifecycleCleanupOrchestrator(LifecycleBlastCleanupSupport):
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def execute(self, route: Route) -> int:
        if route.command in {"stop-all", "blast-all"}:
            return self._execute_full_cleanup(route)
        return self._execute_stop(route)

    def _execute_full_cleanup(self, route: Route) -> int:
        def operation() -> int:
            self.clear_runtime_state(
                command=route.command,
                aggressive=(route.command == "blast-all"),
                route=route,
            )
            print("Stopped runtime state.")
            return 0

        message = (
            "Stopping all services and runtime state..."
            if route.command == "stop-all"
            else "Running blast-all cleanup..."
        )
        return self._run_spinner_operation(
            route=route,
            op_id=f"cleanup.{route.command}",
            message=message,
            operation=operation,
        )

    def _execute_stop(self, route: Route) -> int:
        state = self.runtime._try_load_existing_state(  # type: ignore[attr-defined]
            mode=route.mode,
            strict_mode_match=self.runtime._state_lookup_strict_mode_match(route),  # type: ignore[attr-defined]
        )
        if state is None:
            print("No active runtime state found.")
            return 0

        if route.flags.get("runtime_scope") == "dependencies":
            return self._execute_stop_dependencies(route, state)

        preserve_stopped_dashboard_state = self._should_preserve_stopped_dashboard_state(route)
        selected_dependencies = self._select_dependency_components_for_stop(state, route)
        selected = self._select_services_for_stop(state, route)
        if not selected and not selected_dependencies:
            if not state.services and not state.requirements:
                self.clear_runtime_state(command="stop", aggressive=False)
                print("Stopped runtime state.")
                return 0
            print("No matching services selected for stop.")
            return 1

        def operation() -> int:
            if selected and preserve_stopped_dashboard_state:
                self._remember_dashboard_stopped_services(state, selected)

            if selected:
                self.runtime._terminate_services_from_state(  # type: ignore[attr-defined]
                    state,
                    selected_services=selected,
                    aggressive=False,
                    verify_ownership=True,
                )

            for service_name in list(selected):
                state.services.pop(service_name, None)

            if selected_dependencies:
                self._release_selected_dependency_components(state, selected_dependencies)

            if not bool(route.flags.get("stop_preserve_requirements")):
                remaining_projects = {
                    self.runtime._project_name_from_service(name)  # type: ignore[attr-defined]
                    for name in state.services
                }
                removed_projects = [project for project in state.requirements if project not in remaining_projects]
                for project in removed_projects:
                    self.runtime._release_requirement_ports(state.requirements[project])  # type: ignore[attr-defined]
                    state.requirements.pop(project, None)

            if not state.services and not state.requirements:
                if preserve_stopped_dashboard_state and self._has_dashboard_stopped_services(state):
                    self._state_repository(self.runtime).save_selected_stop_state(  # type: ignore[attr-defined]
                        state=state,
                        emit=self.runtime._emit,  # type: ignore[attr-defined]
                        runtime_map_builder=build_runtime_map,
                    )
                    if selected and selected_dependencies:
                        print("Stopped selected services and dependencies.")
                    elif selected_dependencies:
                        print("Stopped selected dependencies.")
                    else:
                        print("Stopped selected services.")
                    return 0
                self.clear_runtime_state(command="stop", aggressive=False)
                print("Stopped runtime state.")
                return 0

            self._state_repository(self.runtime).save_selected_stop_state(  # type: ignore[attr-defined]
                state=state,
                emit=self.runtime._emit,  # type: ignore[attr-defined]
                runtime_map_builder=build_runtime_map,
            )
            if selected and selected_dependencies:
                print("Stopped selected services and dependencies.")
            elif selected_dependencies:
                print("Stopped selected dependencies.")
            else:
                print("Stopped selected services.")
            return 0

        selected_count = len(selected) + sum(len(items) for items in selected_dependencies.values())
        resource_label = "resource" if selected_count == 1 else "resources"
        message = f"Stopping {selected_count} selected {resource_label}..."
        return self._run_spinner_operation(
            route=route,
            op_id="cleanup.stop",
            message=message,
            operation=operation,
        )

    @staticmethod
    def _should_preserve_stopped_dashboard_state(route: Route) -> bool:
        if bool(route.flags.get("interactive_command")):
            return True
        if bool(route.flags.get("stop_preserve_requirements")):
            return True
        services = route.flags.get("services")
        return isinstance(services, list) and any(str(item).strip() for item in services)

    def _remember_dashboard_stopped_services(self, state: RunState, selected_services: set[str]) -> None:
        if not selected_services:
            return
        raw_existing = state.metadata.get("dashboard_stopped_services")
        existing_items = raw_existing if isinstance(raw_existing, list) else []
        by_name: dict[str, dict[str, str]] = {}
        for item in existing_items:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name", "") or "").strip()
            project = str(item.get("project", "") or "").strip()
            service_type = str(item.get("type", "") or "").strip().lower()
            if name and project and service_type:
                by_name[name] = {"name": name, "project": project, "type": service_type}

        raw_roots = state.metadata.get("project_roots")
        project_roots = dict(raw_roots) if isinstance(raw_roots, Mapping) else {}
        raw_configured_types = state.metadata.get("dashboard_configured_service_types")
        configured_types = {
            str(item).strip().lower()
            for item in (raw_configured_types if isinstance(raw_configured_types, list) else [])
            if str(item).strip()
        }

        for service_name in sorted(selected_services):
            service = state.services.get(service_name)
            if service is None:
                continue
            project = service_project_name(service)
            if not project:
                project = str(self.runtime._project_name_from_service(service_name) or "").strip()  # type: ignore[attr-defined]
            if not project:
                project = self._project_name_from_stopped_service(service_name)
            service_type = self._service_type_from_stopped_service(service_name, service)
            if not project or not service_type:
                continue
            by_name[service_name] = {"name": service_name, "project": project, "type": service_type}
            configured_types.add(service_type)
            if project not in project_roots:
                root = self._project_root_from_stopped_service(service, service_type=service_type)
                if root:
                    project_roots[project] = root

        if by_name:
            state.metadata["dashboard_stopped_services"] = [by_name[name] for name in sorted(by_name)]
        if project_roots:
            state.metadata["project_roots"] = {str(key): str(value) for key, value in project_roots.items()}
        if configured_types:
            state.metadata["dashboard_configured_service_types"] = sorted(configured_types)

    @staticmethod
    def _has_dashboard_stopped_services(state: RunState) -> bool:
        raw = state.metadata.get("dashboard_stopped_services")
        return isinstance(raw, list) and bool(raw)

    @staticmethod
    def _project_name_from_stopped_service(service_name: str) -> str:
        trimmed = str(service_name).strip()
        for suffix in (" Backend", " Frontend"):
            if trimmed.endswith(suffix):
                return trimmed[: -len(suffix)].strip()
        return ""

    @staticmethod
    def _service_type_from_stopped_service(service_name: str, service: object) -> str:
        service_type = service_slug_from_record(service)
        if service_type:
            return service_type
        lowered = str(service_name).strip().lower()
        if lowered.endswith(" backend"):
            return "backend"
        if lowered.endswith(" frontend"):
            return "frontend"
        return ""

    @staticmethod
    def _project_root_from_stopped_service(service: object, *, service_type: str) -> str:
        cwd_raw = str(getattr(service, "cwd", "") or "").strip()
        if not cwd_raw:
            return ""
        cwd = Path(cwd_raw).expanduser()
        if cwd.name.lower() == service_type:
            return str(cwd.parent)
        return str(cwd)

    def _select_services_for_stop(self, state: RunState, route: Route) -> set[str]:
        if route.command != "stop":
            return set(state.services.keys())
        if bool(route.flags.get("all")):
            return set(state.services.keys())

        runtime_scope = route.flags.get("runtime_scope")
        if runtime_scope in {"backend", "frontend"}:
            return {
                name
                for name, service in state.services.items()
                if self._service_matches_runtime_scope(name, service, str(runtime_scope))
            }
        if runtime_scope in {"fullstack", "entire-system"}:
            return set(state.services.keys())
        if runtime_scope == "dependencies":
            return set()

        selected: set[str] = set()
        has_selectors = False
        services_flag = route.flags.get("services")
        if isinstance(services_flag, list):
            has_selectors = has_selectors or bool(services_flag)
            for raw in services_flag:
                target = str(raw).strip().lower()
                if not target:
                    continue
                for name, service in state.services.items():
                    if name.lower() == target or service_matches_selector(service, target):
                        selected.add(name)

        project_names = {name.lower() for name in route.projects}
        selectors_from_passthrough = getattr(self.runtime, "_selectors_from_passthrough", None)
        if callable(selectors_from_passthrough):
            project_names.update(selectors_from_passthrough(route.passthrough_args))
        has_selectors = has_selectors or bool(project_names)
        if project_names:
            for name in state.services:
                project = self.runtime._project_name_from_service(name).lower()  # type: ignore[attr-defined]
                if project and project in project_names:
                    selected.add(name)

        if not selected and has_selectors:
            return set()
        if not selected and self._select_dependency_components_for_stop(state, route):
            return set()
        if not selected:
            selection = self._interactive_stop_selection(route, state)
            if selection is not None:
                if selection.cancelled:
                    return set()
                selected = self._services_from_selection(selection, state)
        if not selected:
            return set(state.services.keys())
        return selected

    def _execute_stop_dependencies(self, route: Route, state: RunState) -> int:
        def operation() -> int:
            if not state.requirements:
                if not state.services:
                    self._state_repository(self.runtime).purge(aggressive=False)
                    release_port_session = getattr(self.runtime, "_release_port_session", None)
                    if callable(release_port_session):
                        release_port_session()
                print("No dependencies found.")
                return 0

            for project in list(state.requirements):
                self._release_requirement_ports(state.requirements[project])
                state.requirements.pop(project, None)

            if state.services:
                self._state_repository(self.runtime).save_selected_stop_state(
                    state=state,
                    emit=self.runtime._emit,  # type: ignore[attr-defined]
                    runtime_map_builder=build_runtime_map,
                )
            else:
                self._state_repository(self.runtime).purge(aggressive=False)
                release_port_session = getattr(self.runtime, "_release_port_session", None)
                if callable(release_port_session):
                    release_port_session()

            print("Stopped dependencies.")
            return 0

        return self._run_spinner_operation(
            route=route,
            op_id="cleanup.stop_dependencies",
            message="Stopping dependencies...",
            operation=operation,
        )

    def _select_dependency_components_for_stop(self, state: RunState, route: Route) -> dict[str, set[str]]:
        raw_components = route.flags.get("stop_dependency_components")
        if not isinstance(raw_components, list):
            return {}
        known_definitions = {definition.id for definition in dependency_definitions()}
        selected: dict[str, set[str]] = {}
        project_key_by_lower = {str(project).strip().casefold(): project for project in state.requirements}
        for raw in raw_components:
            project_name, separator, dependency_id = str(raw).partition(":")
            if not separator:
                continue
            project_key = project_key_by_lower.get(project_name.strip().casefold())
            if project_key is None:
                continue
            normalized_dependency = dependency_id.strip().lower()
            if normalized_dependency not in known_definitions:
                continue
            component = state.requirements[project_key].component(normalized_dependency)
            if not bool(component.get("enabled", False)):
                continue
            selected.setdefault(project_key, set()).add(normalized_dependency)
        return selected

    def _release_selected_dependency_components(
        self,
        state: RunState,
        selected_dependencies: dict[str, set[str]],
    ) -> None:
        for project_name, dependency_ids in selected_dependencies.items():
            requirements = state.requirements.get(project_name)
            if requirements is None:
                continue
            for dependency_id in dependency_ids:
                component = requirements.component(dependency_id)
                if not bool(component.get("enabled", False)):
                    continue
                if not bool(component.get("external")):
                    self._release_requirement_component_ports(component)
                requirements.components[dependency_id] = {}
            if not self._requirements_have_enabled_components(requirements):
                state.requirements.pop(project_name, None)

    def _release_requirement_component_ports(self, component: Mapping[str, object]) -> None:
        ports: set[int] = set()
        final = component.get("final")
        if isinstance(final, int) and final > 0:
            ports.add(final)
        resources = component.get("resources")
        if isinstance(resources, Mapping):
            for value in resources.values():
                if isinstance(value, int) and value > 0:
                    ports.add(value)
        port_planner = getattr(self.runtime, "port_planner", None)
        release = getattr(port_planner, "release", None)
        if not callable(release):
            return
        for port in sorted(ports):
            release(port)

    @staticmethod
    def _requirements_have_enabled_components(requirements: object) -> bool:
        components = getattr(requirements, "components", {})
        if not isinstance(components, Mapping):
            return False
        return any(
            bool(component.get("enabled", False))
            for component in components.values()
            if isinstance(component, Mapping)
        )

    def _release_requirement_ports(self, requirements: object) -> None:
        release = getattr(self.runtime, "_release_requirement_ports", None)
        if callable(release):
            release(requirements)
            return
        release_requirement_ports(self.runtime, requirements)  # type: ignore[arg-type]

    @staticmethod
    def _service_matches_runtime_scope(name: str, service: object, runtime_scope: str) -> bool:
        service_type = str(getattr(service, "type", "") or "").strip().lower()
        if service_type == runtime_scope:
            return True
        lowered_name = str(name).strip().lower()
        return lowered_name.endswith(f" {runtime_scope}")

    def _interactive_stop_selection(self, route: Route, state: RunState) -> TargetSelection | None:
        if not self._interactive_selection_allowed(route):
            return None
        projects = self._project_names_from_state(state)
        services = sorted(state.services.keys())
        return self.runtime._select_grouped_targets(  # type: ignore[attr-defined]
            prompt="Stop services",
            projects=projects,
            services=services,
            allow_all=True,
            multi=True,
        )

    def _interactive_selection_allowed(self, route: Route) -> bool:
        return interactive_selection_allowed(self.runtime, route, allow_dashboard_override=True)

    def _project_names_from_state(self, state: RunState) -> list[object]:
        return project_names_from_state(self.runtime, state)

    def _services_from_selection(self, selection: TargetSelection, state: RunState) -> set[str]:
        return services_from_selection(self.runtime, selection, state)

    def clear_runtime_state(self, *, command: str, aggressive: bool = False, route: Route | None = None) -> None:
        rt = self.runtime
        if command == "stop-all":
            rt._emit("cleanup.stop_all", aggressive=aggressive)  # type: ignore[attr-defined]
        elif aggressive:
            rt._emit("cleanup.blast", aggressive=aggressive)  # type: ignore[attr-defined]
        else:
            rt._emit("cleanup.stop", aggressive=aggressive)  # type: ignore[attr-defined]
        state = rt._try_load_existing_state()  # type: ignore[attr-defined]
        if state is not None:
            rt._terminate_services_from_state(  # type: ignore[attr-defined]
                state,
                selected_services=None,
                aggressive=aggressive,
                verify_ownership=not aggressive,
            )

        if aggressive and self.blast_all_ecosystem_enabled():
            self.blast_all_ecosystem_cleanup(route=route)
        elif command == "stop-all" and route is not None and bool(route.flags.get("stop_all_remove_volumes")):
            rt._emit("cleanup.stop_all.remove_volumes", requested=True)  # type: ignore[attr-defined]
            volume_route = Route(
                command=route.command,
                mode=route.mode,
                raw_args=route.raw_args,
                passthrough_args=route.passthrough_args,
                projects=route.projects,
                flags={
                    **route.flags,
                    "blast_keep_worktree_volumes": False,
                    "blast_remove_main_volumes": True,
                },
            )
            removed = self.blast_all_docker_cleanup(route=volume_route)
            rt._emit("cleanup.stop_all.remove_volumes.finish", removed=removed)  # type: ignore[attr-defined]

        if aggressive:
            self.release_all_runtime_ports()
        else:
            rt._release_port_session()  # type: ignore[attr-defined]
        self._state_repository(rt).purge(aggressive=aggressive)  # type: ignore[attr-defined]
        if aggressive:
            self.blast_all_purge_legacy_state_artifacts()

    def _run_spinner_operation(
        self,
        *,
        route: Route,
        op_id: str,
        message: str,
        operation: Callable[[], int],
    ) -> int:
        rt = self.runtime
        spinner_policy = resolve_spinner_policy(getattr(rt, "env", {}))
        emit_spinner_policy(
            getattr(rt, "_emit", None),
            spinner_policy,
            context={"component": "lifecycle_cleanup", "command": route.command, "op_id": op_id},
        )

        with (
            use_spinner_policy(spinner_policy),
            spinner(
                message,
                enabled=spinner_policy.enabled,
                start_immediately=False,
            ) as active_spinner,
        ):
            if spinner_policy.enabled:
                active_spinner.start()
                rt._emit(  # type: ignore[attr-defined]
                    "ui.spinner.lifecycle",
                    component="lifecycle_cleanup",
                    command=route.command,
                    op_id=op_id,
                    state="start",
                    message=message,
                )
            try:
                code = operation()
            except Exception:
                if spinner_policy.enabled:
                    active_spinner.fail("Cleanup failed")
                    rt._emit(  # type: ignore[attr-defined]
                        "ui.spinner.lifecycle",
                        component="lifecycle_cleanup",
                        command=route.command,
                        op_id=op_id,
                        state="fail",
                        message="Cleanup failed",
                    )
                    rt._emit(  # type: ignore[attr-defined]
                        "ui.spinner.lifecycle",
                        component="lifecycle_cleanup",
                        command=route.command,
                        op_id=op_id,
                        state="stop",
                    )
                raise

            if spinner_policy.enabled:
                if code == 0:
                    active_spinner.succeed("Cleanup completed")
                    rt._emit(  # type: ignore[attr-defined]
                        "ui.spinner.lifecycle",
                        component="lifecycle_cleanup",
                        command=route.command,
                        op_id=op_id,
                        state="success",
                        message="Cleanup completed",
                    )
                else:
                    active_spinner.fail("Cleanup failed")
                    rt._emit(  # type: ignore[attr-defined]
                        "ui.spinner.lifecycle",
                        component="lifecycle_cleanup",
                        command=route.command,
                        op_id=op_id,
                        state="fail",
                        message="Cleanup failed",
                    )
                rt._emit(  # type: ignore[attr-defined]
                    "ui.spinner.lifecycle",
                    component="lifecycle_cleanup",
                    command=route.command,
                    op_id=op_id,
                    state="stop",
                )
            return code

    @staticmethod
    def _state_repository(runtime: object) -> _StateRepositoryProtocol:
        runtime_context = getattr(runtime, "runtime_context", None)
        candidate = getattr(runtime_context, "state_repository", None)
        if candidate is None:
            candidate = getattr(runtime, "state_repository", None)
        if candidate is None:
            raise RuntimeError("state repository dependency is not configured")
        return cast(_StateRepositoryProtocol, candidate)

    @staticmethod
    def _process_runtime(runtime: object) -> _ProcessRuntimeProtocol:
        runtime_context = getattr(runtime, "runtime_context", None)
        candidate = getattr(runtime_context, "process_runtime", None)
        if candidate is None:
            candidate = getattr(runtime, "process_runner", None)
        if candidate is None:
            raise RuntimeError("process runtime dependency is not configured")
        return cast(_ProcessRuntimeProtocol, candidate)
