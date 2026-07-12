from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Callable, Mapping, cast

from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.runtime.engine_runtime_lifecycle_support import release_requirement_ports
from envctl_engine.runtime.lifecycle_blast_support import LifecycleBlastCleanupSupport
from envctl_engine.runtime.lifecycle_dependency_stop import (
    release_requirement_component_ports,
    release_selected_dependency_components,
    requirements_have_enabled_components,
    select_dependency_components_for_stop,
    stop_requirement_component_containers,
)
from envctl_engine.runtime.lifecycle_requirement_ports import requirement_component_port_owners
from envctl_engine.runtime.lifecycle_full_cleanup import clear_runtime_state as clear_full_runtime_state
from envctl_engine.runtime.lifecycle_service_stop_selection import (
    project_selectors_from_route,
    select_services_for_stop,
    service_matches_runtime_scope,
)
from envctl_engine.runtime.lifecycle_service_termination import unconfirmed_service_names
from envctl_engine.runtime.lifecycle_stopped_metadata import (
    has_dashboard_stopped_services,
    project_name_from_stopped_service,
    project_root_from_stopped_service,
    remember_dashboard_stopped_services,
    service_type_from_stopped_service,
    should_preserve_stopped_dashboard_state,
)
from envctl_engine.runtime.lifecycle_targeted_state import LifecycleTargetedStateSupport
from envctl_engine.runtime.runtime_context import (
    resolve_port_allocator,
    resolve_process_runtime,
    resolve_state_repository,
)
from envctl_engine.shared.protocols import PortAllocator, ProcessRuntime, StateRepository
from envctl_engine.shared.services import service_matches_selector
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.lookup import call_state_loader
from envctl_engine.state.models import RequirementsResult, RunState
from envctl_engine.ui.selection_support import (
    interactive_selection_allowed,
    project_names_from_state,
    services_from_selection,
)
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI  # noqa: F401
from envctl_engine.ui.selection_types import TargetSelection
from envctl_engine.ui.spinner import Spinner, spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy


class LifecycleCleanupOrchestrator(
    LifecycleTargetedStateSupport,
    LifecycleBlastCleanupSupport,
):
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def execute(self, route: Route) -> int:
        if route.command in {"stop-all", "blast-all"}:
            return self._execute_full_cleanup(route)
        return self._execute_stop(route)

    def _execute_full_cleanup(self, route: Route) -> int:
        def operation() -> int:
            completed = self.clear_runtime_state(
                command=route.command,
                aggressive=(route.command == "blast-all"),
                route=route,
            )
            if completed:
                print("Stopped runtime state.")
                return 0
            print("Runtime cleanup is incomplete; failed resources remain tracked.")
            return 1

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
        targeted_states = self._targeted_active_states(route)
        if targeted_states:
            result = 0
            for state in targeted_states:
                result = max(result, self._execute_stop_state(route, state))
            return result

        state = call_state_loader(
            self.runtime._try_load_existing_state,  # type: ignore[attr-defined]
            mode=route.mode,
            strict_mode_match=self.runtime._state_lookup_strict_mode_match(route),  # type: ignore[attr-defined]
            project_names=route.projects or None,
        )
        if state is None:
            print("No active runtime state found.")
            return 0

        return self._execute_stop_state(route, state)

    def _targeted_active_states(self, route: Route) -> list[RunState]:
        selected_projects = {str(project).strip().casefold() for project in route.projects if str(project).strip()}
        if not selected_projects:
            return []
        repository = self._state_repository(self.runtime)
        load_all = getattr(repository, "load_all", None)
        if not callable(load_all):
            return []
        matching_states = self._states_matching_projects(
            [state for state in load_all(mode=route.mode) if isinstance(state, RunState)],
            selected_projects,
        )
        if matching_states:
            return matching_states
        if self.runtime._state_lookup_strict_mode_match(route):  # type: ignore[attr-defined]
            return []

        fallback_state = call_state_loader(
            self.runtime._try_load_existing_state,  # type: ignore[attr-defined]
            mode=route.mode,
            strict_mode_match=False,
            project_names=route.projects,
        )
        if not isinstance(fallback_state, RunState) or fallback_state.mode == route.mode:
            return []
        return self._states_matching_projects(
            [state for state in load_all(mode=fallback_state.mode) if isinstance(state, RunState)],
            selected_projects,
        )

    def _states_matching_projects(
        self,
        states: Iterable[RunState],
        selected_projects: set[str],
    ) -> list[RunState]:
        return [
            state
            for state in states
            if selected_projects.intersection(
                str(getattr(project, "name", project)).strip().casefold()
                for project in self._project_names_from_state(state)
            )
        ]

    def _execute_stop_state(self, route: Route, state: RunState) -> int:

        if route.flags.get("runtime_scope") == "dependencies":
            return self._execute_stop_dependencies(route, state)

        owned_projects = self._owned_project_names(state)
        dependency_project_keys, has_dependency_project_scope = self._dependency_scope_project_keys(state, route)
        if route.flags.get("runtime_scope") == "entire-system" and has_dependency_project_scope:
            targeted_project_keys = frozenset(
                project for project in dependency_project_keys if project in owned_projects
            )
        else:
            targeted_project_keys = frozenset(
                str(project).strip().casefold()
                for project in route.projects
                if str(project).strip().casefold() in owned_projects
            )
        preserve_stopped_dashboard_state = self._should_preserve_stopped_dashboard_state(route)
        selected_dependencies = self._select_dependency_components_for_stop(
            state,
            route,
            requested_projects=(
                dependency_project_keys
                if route.flags.get("runtime_scope") == "entire-system" and has_dependency_project_scope
                else None
            ),
        )
        selected = self._select_services_for_stop(state, route)
        if not selected and not selected_dependencies:
            if targeted_project_keys and self._targeted_projects_have_no_managed_resources(
                state,
                targeted_project_keys,
            ):
                self._remove_targeted_requirements(state, targeted_project_keys)
                state_remains = self._persist_targeted_project_state(
                    state,
                    owned_projects=owned_projects,
                    targeted_project_keys=targeted_project_keys,
                )
                print("Stopped selected project state." if state_remains else "Stopped runtime state.")
                return 0
            has_enabled_requirements = any(
                self._requirements_have_enabled_components(requirements) for requirements in state.requirements.values()
            )
            if not state.services and not has_enabled_requirements:
                self._deactivate_runtime_state(state)
                print("Stopped runtime state.")
                return 0
            print("No matching services selected for stop.")
            return 1

        def operation() -> int:
            self.runtime._emit(  # type: ignore[attr-defined]
                "cleanup.stop",
                aggressive=False,
                run_id=state.run_id,
            )
            failed_services: set[str] = set()
            if selected:
                termination_result = self.runtime._terminate_services_from_state(  # type: ignore[attr-defined]
                    state,
                    selected_services=selected,
                    aggressive=False,
                    verify_ownership=True,
                )
                failed_services = unconfirmed_service_names(termination_result, selected)

            stopped_services = selected.difference(failed_services)
            if stopped_services and preserve_stopped_dashboard_state:
                self._remember_dashboard_stopped_services(state, stopped_services)

            for service_name in stopped_services:
                state.services.pop(service_name, None)

            if selected_dependencies and not failed_services:
                self._release_selected_dependency_components(state, selected_dependencies)

            if not failed_services and not bool(route.flags.get("stop_preserve_requirements")):
                remaining_projects = {
                    self._project_name_for_service(name, service) for name, service in state.services.items()
                }
                removed_projects = [
                    project
                    for project, requirements in state.requirements.items()
                    if self._requirement_project_key(project, requirements) not in remaining_projects
                    and (
                        not targeted_project_keys
                        or self._requirement_project_key(project, requirements) in targeted_project_keys
                    )
                ]
                for project in removed_projects:
                    self.runtime._release_requirement_ports(state.requirements[project])  # type: ignore[attr-defined]
                    state.requirements.pop(project, None)

            if targeted_project_keys:
                self._persist_targeted_project_state(
                    state,
                    owned_projects=owned_projects,
                    targeted_project_keys=targeted_project_keys,
                )
                if failed_services:
                    print("Could not safely stop: " + ", ".join(sorted(failed_services)))
                    return 1
                if stopped_services and selected_dependencies:
                    print("Stopped selected services and dependencies.")
                elif selected_dependencies:
                    print("Stopped selected dependencies.")
                elif stopped_services:
                    print("Stopped selected services.")
                else:
                    print("Stopped selected project state.")
                return 0

            if not state.services and not state.requirements:
                if preserve_stopped_dashboard_state and self._has_dashboard_stopped_services(state):
                    self._save_selected_stop_state(state)
                    if stopped_services and selected_dependencies:
                        print("Stopped selected services and dependencies.")
                    elif selected_dependencies:
                        print("Stopped selected dependencies.")
                    elif stopped_services:
                        print("Stopped selected services.")
                    else:
                        print("No selected service could be stopped.")
                    return 0
                self._deactivate_runtime_state(state)
                print("Stopped runtime state.")
                return 0

            self._save_selected_stop_state(state)
            if failed_services:
                print("Could not safely stop: " + ", ".join(sorted(failed_services)))
                return 1
            if stopped_services and selected_dependencies:
                print("Stopped selected services and dependencies.")
            elif selected_dependencies:
                print("Stopped selected dependencies.")
            elif stopped_services:
                print("Stopped selected services.")
            else:
                print("Stopped selected dependencies.")
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
        def selected_services_from_ui_selection(selection: object, selected_state: RunState) -> set[str]:
            return self._services_from_selection(cast(TargetSelection, selection), selected_state)

        return select_services_for_stop(
            state,
            route,
            project_name_from_service_fn=lambda service_name: self.runtime._project_name_from_service(  # type: ignore[attr-defined]
                service_name
            ),
            selectors_from_passthrough_fn=self._passthrough_project_selectors,
            interactive_stop_selection_fn=self._interactive_stop_selection,
            services_from_selection_fn=selected_services_from_ui_selection,
        )

    def _passthrough_project_selectors(self, args: list[str]) -> set[str]:
        selectors_from_passthrough = getattr(self.runtime, "_selectors_from_passthrough", None)
        if callable(selectors_from_passthrough):
            result = selectors_from_passthrough(args)
            if isinstance(result, str):
                return {result}
            if isinstance(result, Iterable):
                return {str(item).strip().casefold() for item in result if str(item).strip()}
        selectors: set[str] = set()
        for token in args:
            if str(token).startswith("-"):
                continue
            selectors.update(part.strip().casefold() for part in str(token).split(",") if part.strip())
        return selectors

    def _dependency_scope_project_keys(self, state: RunState, route: Route) -> tuple[frozenset[str], bool]:
        project_keys = project_selectors_from_route(
            route,
            selectors_from_passthrough_fn=self._passthrough_project_selectors,
        )
        services_flag = route.flags.get("services")
        has_selectors = bool(project_keys)
        if isinstance(services_flag, list):
            service_selectors = [str(selector).strip() for selector in services_flag if str(selector).strip()]
            has_selectors = has_selectors or bool(service_selectors)
            for selector in service_selectors:
                for name, service in state.services.items():
                    if name.casefold() == selector.casefold() or service_matches_selector(service, selector):
                        project = self._project_name_for_service(name, service)
                        if project:
                            project_keys.add(project)
        return frozenset(project_keys), has_selectors

    def _execute_stop_dependencies(self, route: Route, state: RunState) -> int:
        def operation() -> int:
            if not state.requirements:
                if not state.services:
                    self._deactivate_runtime_state(state)
                print("No dependencies found.")
                return 0

            targeted_project_keys, has_targeted_scope = self._dependency_scope_project_keys(state, route)
            owned_projects = self._owned_project_names(state)
            matching_requirement_keys = {
                storage_key
                for storage_key, requirements in state.requirements.items()
                if self._requirement_project_key(storage_key, requirements) in targeted_project_keys
            }
            if has_targeted_scope and not matching_requirement_keys:
                print("No matching dependencies found.")
                return 1
            removed_count = 0
            for storage_key in list(state.requirements):
                requirements = state.requirements[storage_key]
                requirement_project = self._requirement_project_key(storage_key, requirements)
                if has_targeted_scope and requirement_project not in targeted_project_keys:
                    continue
                for definition in dependency_definitions():
                    component = requirements.component(definition.id)
                    if bool(component.get("enabled", False)):
                        self._stop_requirement_component_containers(component)
                self._release_requirement_ports(requirements)
                state.requirements.pop(storage_key, None)
                removed_count += 1

            if has_targeted_scope:
                self._persist_targeted_project_state(
                    state,
                    owned_projects=owned_projects,
                    targeted_project_keys=targeted_project_keys,
                )
            elif state.services or state.requirements:
                self._save_selected_stop_state(state)
            else:
                self._deactivate_runtime_state(state)

            print("Stopped dependencies." if removed_count else "No matching dependencies found.")
            return 0

        return self._run_spinner_operation(
            route=route,
            op_id="cleanup.stop_dependencies",
            message="Stopping dependencies...",
            operation=operation,
        )

    def _select_dependency_components_for_stop(
        self,
        state: RunState,
        route: Route,
        *,
        requested_projects: Iterable[str] | None = None,
    ) -> dict[str, set[str]]:
        return select_dependency_components_for_stop(
            state,
            route,
            requested_projects=requested_projects,
        )

    def _release_selected_dependency_components(
        self,
        state: RunState,
        selected_dependencies: dict[str, set[str]],
    ) -> None:
        release_selected_dependency_components(
            state,
            selected_dependencies,
            release_component_ports_fn=self._release_requirement_component_ports,
            stop_component_fn=self._stop_requirement_component_containers,
        )

    def _stop_requirement_component_containers(self, component: Mapping[str, object]) -> None:
        stop_requirement_component_containers(self.runtime, component)

    def _stop_requirement_component_containers_best_effort(self, component: Mapping[str, object]) -> bool:
        try:
            self._stop_requirement_component_containers(component)
            return True
        except Exception as exc:  # noqa: BLE001
            component_id = str(component.get("id") or "dependency").strip() or "dependency"
            detail = str(exc).strip() or exc.__class__.__name__
            self.runtime._emit(  # type: ignore[attr-defined]
                "cleanup.dependency_container.warning",
                component=component_id,
                detail=detail,
            )
            print(f"Warning: could not stop {component_id} container during cleanup: {detail}")
            return False

    def _stop_requirement_containers(
        self,
        requirements: RequirementsResult,
        *,
        best_effort: bool = False,
    ) -> bool:
        stopped = True
        for definition in dependency_definitions():
            component = requirements.component(definition.id)
            if bool(component.get("enabled", False)):
                if best_effort:
                    stopped = self._stop_requirement_component_containers_best_effort(component) and stopped
                else:
                    self._stop_requirement_component_containers(component)
        return stopped

    def _release_requirement_component_ports(
        self,
        requirements: RequirementsResult,
        dependency_id: str,
        component: Mapping[str, object],
    ) -> None:
        port_allocator = self._port_allocator(self.runtime)
        release_requirement_component_ports(
            component,
            port_planner=port_allocator,
            owner_candidates=requirement_component_port_owners(requirements, dependency_id),
        )

    @staticmethod
    def _requirements_have_enabled_components(requirements: object) -> bool:
        return requirements_have_enabled_components(requirements)

    def _release_requirement_ports(self, requirements: RequirementsResult) -> None:
        release = getattr(self.runtime, "_release_requirement_ports", None)
        if callable(release):
            release(requirements)
            return
        release_requirement_ports(self.runtime, requirements)

    def _release_requirement_ports_best_effort(self, requirements: RequirementsResult) -> bool:
        try:
            self._release_requirement_ports(requirements)
            return True
        except Exception as exc:  # noqa: BLE001
            project = str(getattr(requirements, "project", "") or "dependency").strip() or "dependency"
            detail = str(exc).strip() or exc.__class__.__name__
            self.runtime._emit(  # type: ignore[attr-defined]
                "cleanup.requirement_ports.warning",
                project=project,
                detail=detail,
            )
            print(f"Warning: could not release {project} dependency ports during cleanup: {detail}")
            return False

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

    def clear_runtime_state(
        self,
        *,
        command: str,
        aggressive: bool = False,
        route: Route | None = None,
    ) -> bool:
        return clear_full_runtime_state(
            self,
            command=command,
            aggressive=aggressive,
            route=route,
        )

    @staticmethod
    def _has_active_runs(repository: object) -> bool:
        has_active_runs = getattr(repository, "has_active_runs", None)
        if callable(has_active_runs):
            return bool(has_active_runs())
        load_all = getattr(repository, "load_all", None)
        return bool(load_all()) if callable(load_all) else True

    def _purge_runtime_state(self, *, aggressive: bool) -> None:
        self._state_repository(self.runtime).purge(aggressive=aggressive)
        # Purging means no tracked run remains in this repository scope. Port
        # locks were created by the original startup process (and therefore a
        # different PortPlanner session), so releasing only this command's
        # session leaves unused/disabled stack locks behind indefinitely. The
        # registry commit happens first so a failed purge cannot erase locks
        # that still protect an authoritative active state.
        self.release_all_runtime_ports()

    def _deactivate_runtime_state(
        self,
        state: RunState,
        *,
        release_session_when_empty: bool = True,
    ) -> None:
        repository = self._state_repository(self.runtime)
        source_run_ids = [
            str(run_id).strip()
            for run_id in (
                state.metadata.get("state_source_run_ids")
                if isinstance(state.metadata.get("state_source_run_ids"), list)
                else []
            )
            if str(run_id).strip()
        ]
        run_ids = sorted({state.run_id, *source_run_ids})
        deactivate_many = getattr(repository, "deactivate_runs", None)
        deactivate = getattr(repository, "deactivate_run", None)
        if callable(deactivate_many) or callable(deactivate):
            if callable(deactivate_many):
                deactivate_many(run_ids)
            elif callable(deactivate):
                for run_id in run_ids:
                    deactivate(run_id)
            if release_session_when_empty and not self._has_active_runs(repository):
                # The final run may have been started by an earlier process and
                # therefore a different planner session. At this point the
                # repository proves the whole scope inactive, so every scoped
                # lock is stale ownership rather than another live run's lock.
                self.release_all_runtime_ports()
            return
        self._purge_runtime_state(aggressive=False)

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
                self._emit_spinner_lifecycle(route=route, op_id=op_id, state="start", message=message)
            try:
                code = operation()
            except Exception:
                if spinner_policy.enabled:
                    self._finish_spinner_operation(
                        active_spinner,
                        route=route,
                        op_id=op_id,
                        success=False,
                    )
                raise

            if spinner_policy.enabled:
                self._finish_spinner_operation(
                    active_spinner,
                    route=route,
                    op_id=op_id,
                    success=(code == 0),
                )
            return code

    def _finish_spinner_operation(
        self,
        active_spinner: Spinner,
        *,
        route: Route,
        op_id: str,
        success: bool,
    ) -> None:
        if success:
            active_spinner.succeed("Cleanup completed")  # type: ignore[attr-defined]
            self._emit_spinner_lifecycle(
                route=route,
                op_id=op_id,
                state="success",
                message="Cleanup completed",
            )
        else:
            active_spinner.fail("Cleanup failed")  # type: ignore[attr-defined]
            self._emit_spinner_lifecycle(
                route=route,
                op_id=op_id,
                state="fail",
                message="Cleanup failed",
            )
        self._emit_spinner_lifecycle(route=route, op_id=op_id, state="stop")

    def _emit_spinner_lifecycle(
        self,
        *,
        route: Route,
        op_id: str,
        state: str,
        message: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "component": "lifecycle_cleanup",
            "command": route.command,
            "op_id": op_id,
            "state": state,
        }
        if message is not None:
            payload["message"] = message
        self.runtime._emit("ui.spinner.lifecycle", **payload)  # type: ignore[attr-defined]

    @staticmethod
    def _state_repository(runtime: object) -> StateRepository:
        return resolve_state_repository(runtime)

    @staticmethod
    def _process_runtime(runtime: object) -> ProcessRuntime:
        return resolve_process_runtime(runtime)

    @staticmethod
    def _port_allocator(runtime: object) -> PortAllocator:
        return resolve_port_allocator(runtime)
