from __future__ import annotations

from typing import Any, Callable, Mapping

from envctl_engine.runtime.lifecycle_blast_support import LifecycleBlastCleanupSupport
from envctl_engine.runtime.engine_runtime_lifecycle_support import release_requirement_ports
from envctl_engine.runtime.lifecycle_dependency_stop import (
    release_requirement_component_ports,
    release_selected_dependency_components,
    requirements_have_enabled_components,
    select_dependency_components_for_stop,
)
from envctl_engine.runtime.lifecycle_service_stop_selection import (
    select_services_for_stop,
    service_matches_runtime_scope,
)
from envctl_engine.runtime.lifecycle_stopped_metadata import (
    has_dashboard_stopped_services,
    project_name_from_stopped_service,
    project_root_from_stopped_service,
    remember_dashboard_stopped_services,
    service_type_from_stopped_service,
    should_preserve_stopped_dashboard_state,
)
from envctl_engine.runtime.runtime_context import (
    resolve_port_allocator,
    resolve_process_runtime,
    resolve_state_repository,
)
from envctl_engine.shared.protocols import PortAllocator, ProcessRuntime, StateRepository
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.selection_support import (
    interactive_selection_allowed,
    project_names_from_state,
    services_from_selection,
)
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI  # noqa: F401
from envctl_engine.ui.selection_types import TargetSelection
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy


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
        return should_preserve_stopped_dashboard_state(route)

    def _remember_dashboard_stopped_services(self, state: RunState, selected_services: set[str]) -> None:
        remember_dashboard_stopped_services(
            state,
            selected_services,
            project_name_from_service_fn=lambda service_name: str(
                self.runtime._project_name_from_service(service_name) or ""  # type: ignore[attr-defined]
            ).strip(),
        )

    @staticmethod
    def _has_dashboard_stopped_services(state: RunState) -> bool:
        return has_dashboard_stopped_services(state)

    @staticmethod
    def _project_name_from_stopped_service(service_name: str) -> str:
        return project_name_from_stopped_service(service_name)

    @staticmethod
    def _service_type_from_stopped_service(service_name: str, service: object) -> str:
        return service_type_from_stopped_service(service_name, service)

    @staticmethod
    def _project_root_from_stopped_service(service: object, *, service_type: str) -> str:
        return project_root_from_stopped_service(service, service_type=service_type)

    def _select_services_for_stop(self, state: RunState, route: Route) -> set[str]:
        selectors_from_passthrough = getattr(self.runtime, "_selectors_from_passthrough", None)
        return select_services_for_stop(
            state,
            route,
            project_name_from_service_fn=lambda service_name: self.runtime._project_name_from_service(  # type: ignore[attr-defined]
                service_name
            ),
            selectors_from_passthrough_fn=(
                selectors_from_passthrough if callable(selectors_from_passthrough) else lambda _args: set()
            ),
            interactive_stop_selection_fn=self._interactive_stop_selection,
            services_from_selection_fn=self._services_from_selection,
        )

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
        return select_dependency_components_for_stop(state, route)

    def _release_selected_dependency_components(
        self,
        state: RunState,
        selected_dependencies: dict[str, set[str]],
    ) -> None:
        release_selected_dependency_components(
            state,
            selected_dependencies,
            release_component_ports_fn=self._release_requirement_component_ports,
        )

    def _release_requirement_component_ports(self, component: Mapping[str, object]) -> None:
        port_allocator = self._port_allocator(self.runtime)
        release_requirement_component_ports(component, release_port_fn=port_allocator.release)

    @staticmethod
    def _requirements_have_enabled_components(requirements: object) -> bool:
        return requirements_have_enabled_components(requirements)

    def _release_requirement_ports(self, requirements: object) -> None:
        release = getattr(self.runtime, "_release_requirement_ports", None)
        if callable(release):
            release(requirements)
            return
        release_requirement_ports(self.runtime, requirements)  # type: ignore[arg-type]

    @staticmethod
    def _service_matches_runtime_scope(name: str, service: object, runtime_scope: str) -> bool:
        return service_matches_runtime_scope(name, service, runtime_scope)

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
    def _state_repository(runtime: object) -> StateRepository:
        return resolve_state_repository(runtime)

    @staticmethod
    def _process_runtime(runtime: object) -> ProcessRuntime:
        return resolve_process_runtime(runtime)

    @staticmethod
    def _port_allocator(runtime: object) -> PortAllocator:
        return resolve_port_allocator(runtime)
