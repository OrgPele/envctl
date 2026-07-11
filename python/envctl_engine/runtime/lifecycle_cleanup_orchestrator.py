from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Callable, Mapping, cast

from envctl_engine.runtime.lifecycle_blast_support import LifecycleBlastCleanupSupport
from envctl_engine.runtime.engine_runtime_lifecycle_support import release_requirement_ports
from envctl_engine.runtime.lifecycle_dependency_stop import (
    release_requirement_component_ports,
    release_selected_dependency_components,
    requirements_have_enabled_components,
    select_dependency_components_for_stop,
)
from envctl_engine.runtime.lifecycle_requirement_ports import requirement_component_port_owners
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
from envctl_engine.runtime.lifecycle_targeted_state import LifecycleTargetedStateSupport
from envctl_engine.runtime.runtime_context import (
    resolve_port_allocator,
    resolve_process_runtime,
    resolve_state_repository,
)
from envctl_engine.shared.protocols import PortAllocator, ProcessRuntime, StateRepository
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.lookup import call_state_loader
from envctl_engine.state.models import RequirementsResult, RunState
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.ui.selection_support import (
    interactive_selection_allowed,
    project_names_from_state,
    services_from_selection,
)
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI  # noqa: F401
from envctl_engine.ui.selection_types import TargetSelection
from envctl_engine.ui.spinner import Spinner, spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy


class LifecycleCleanupOrchestrator(LifecycleTargetedStateSupport, LifecycleBlastCleanupSupport):
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
            print("Runtime cleanup is incomplete; failed services remain tracked.")
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
        targeted_project_keys = frozenset(
            str(project).strip().casefold()
            for project in route.projects
            if str(project).strip().casefold() in owned_projects
        )
        preserve_stopped_dashboard_state = self._should_preserve_stopped_dashboard_state(route)
        selected_dependencies = self._select_dependency_components_for_stop(state, route)
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
                if isinstance(termination_result, set):
                    failed_services = {str(name) for name in termination_result}

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
        selectors_from_passthrough = getattr(self.runtime, "_selectors_from_passthrough", None)

        def selectors_from_passthrough_args(args: list[str]) -> Iterable[str]:
            if not callable(selectors_from_passthrough):
                return set()
            result = selectors_from_passthrough(args)
            if isinstance(result, str):
                return {result}
            if isinstance(result, Iterable):
                return cast(Iterable[str], result)
            return set()

        def selected_services_from_ui_selection(selection: object, selected_state: RunState) -> set[str]:
            return self._services_from_selection(cast(TargetSelection, selection), selected_state)

        return select_services_for_stop(
            state,
            route,
            project_name_from_service_fn=lambda service_name: self.runtime._project_name_from_service(  # type: ignore[attr-defined]
                service_name
            ),
            selectors_from_passthrough_fn=selectors_from_passthrough_args,
            interactive_stop_selection_fn=self._interactive_stop_selection,
            services_from_selection_fn=selected_services_from_ui_selection,
        )

    def _execute_stop_dependencies(self, route: Route, state: RunState) -> int:
        def operation() -> int:
            if not state.requirements:
                if not state.services:
                    self._deactivate_runtime_state(state)
                print("No dependencies found.")
                return 0

            for project in list(state.requirements):
                self._release_requirement_ports(state.requirements[project])
                state.requirements.pop(project, None)

            if state.services:
                self._save_selected_stop_state(state)
            else:
                self._deactivate_runtime_state(state)

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

    def clear_runtime_state(self, *, command: str, aggressive: bool = False, route: Route | None = None) -> bool:
        rt = self.runtime
        if command == "stop-all":
            rt._emit("cleanup.stop_all", aggressive=aggressive)  # type: ignore[attr-defined]
        elif aggressive:
            rt._emit("cleanup.blast", aggressive=aggressive)  # type: ignore[attr-defined]
        else:
            rt._emit("cleanup.stop", aggressive=aggressive)  # type: ignore[attr-defined]
        state_repository = self._state_repository(rt)
        load_all = getattr(state_repository, "load_all", None)
        mode_filter = route.mode if command == "stop-all" and route is not None else None
        if callable(load_all):
            states = [state for state in load_all(mode=mode_filter) if isinstance(state, RunState)]
        else:
            states = []
        if not states:
            state = call_state_loader(
                rt._try_load_existing_state,  # type: ignore[attr-defined]
                mode=mode_filter,
                strict_mode_match=mode_filter is not None,
            )
            states = [state] if isinstance(state, RunState) else []
        seen_run_ids: set[str] = set()
        failed_by_run: dict[str, set[str]] = {}
        for state in states:
            if state.run_id in seen_run_ids:
                continue
            seen_run_ids.add(state.run_id)
            termination_result = rt._terminate_services_from_state(  # type: ignore[attr-defined]
                state,
                selected_services=None,
                aggressive=aggressive,
                verify_ownership=not aggressive,
            )
            failed_services = (
                {str(name) for name in termination_result} if isinstance(termination_result, set) else set()
            )
            if not failed_services:
                requirements_to_release = list(state.requirements.values())
                self._deactivate_runtime_state(state, release_session_when_empty=False)
                for requirements in requirements_to_release:
                    self._release_requirement_ports(requirements)
                continue
            failed_by_run[state.run_id] = failed_services
            state.services = {name: service for name, service in state.services.items() if name in failed_services}
            failed_projects = {
                project_name
                for name, service in state.services.items()
                if (project_name := self._project_name_for_service(name, service))
            }
            requirements_to_release: list[RequirementsResult] = []
            retained_requirements: dict[str, RequirementsResult] = {}
            for project, requirements in state.requirements.items():
                requirement_project = str(getattr(requirements, "project", "") or project).strip().casefold()
                if not failed_projects or requirement_project in failed_projects:
                    retained_requirements[project] = requirements
                else:
                    requirements_to_release.append(requirements)
            state.requirements = {project: requirements for project, requirements in retained_requirements.items()}
            state_repository.save_selected_stop_state(
                state=state,
                emit=rt._emit,  # type: ignore[attr-defined]
                runtime_map_builder=lambda raw_state: build_runtime_map(cast(RunState, raw_state)),
            )
            for requirements in requirements_to_release:
                self._release_requirement_ports(requirements)

        if failed_by_run:
            rt._emit(  # type: ignore[attr-defined]
                "cleanup.incomplete",
                failed_services={run_id: sorted(names) for run_id, names in failed_by_run.items()},
            )
            return False

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

        if aggressive or command != "stop-all" or not self._has_active_runs(state_repository):
            self._purge_runtime_state(aggressive=aggressive)
        repository = self._state_repository(rt)
        if aggressive and getattr(repository, "compat_mode", None) == getattr(
            repository,
            "COMPAT_READ_WRITE",
            "compat_read_write",
        ):
            self.blast_all_purge_legacy_state_artifacts()
        return True

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
