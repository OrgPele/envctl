from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, cast

from envctl_engine.shared.services import resolve_service_project_name
from envctl_engine.state.models import RequirementsResult, RunState
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.state.state_aggregation import filter_state_to_owned_projects


class LifecycleTargetedStateSupport:
    """Own project-scoped state reduction after targeted lifecycle stops."""

    runtime: Any = cast(Any, None)

    def _project_name_for_service(self, name: str, service: object) -> str:
        return resolve_service_project_name(
            name,
            service,
            project_name_from_service=self.runtime._project_name_from_service,
        ).casefold()

    def _save_selected_stop_state(
        self,
        state: RunState,
        *,
        authoritative_project_names: list[str] | None = None,
    ) -> None:
        owner = cast(Any, self)
        repository = owner._state_repository(self.runtime)

        def runtime_map_builder(raw_state: object) -> dict[str, object]:
            return build_runtime_map(cast(RunState, raw_state))

        if authoritative_project_names is None:
            repository.save_selected_stop_state(
                state=state,
                emit=self.runtime._emit,
                runtime_map_builder=runtime_map_builder,
            )
            return
        repository.save_selected_stop_state(
            state=state,
            emit=self.runtime._emit,
            runtime_map_builder=runtime_map_builder,
            authoritative_project_names=authoritative_project_names,
        )

    def _persist_targeted_project_state(
        self,
        state: RunState,
        *,
        owned_projects: dict[str, str],
        targeted_project_keys: frozenset[str],
    ) -> bool:
        owner = cast(Any, self)
        active_project_keys = self._active_project_keys(state)
        remaining_keys = (set(owned_projects).difference(targeted_project_keys)).union(
            targeted_project_keys.intersection(active_project_keys)
        )
        if not remaining_keys:
            for requirements in state.requirements.values():
                owner._release_requirement_ports(requirements)
            owner._deactivate_runtime_state(state)
            return False

        remaining_names = [owned_projects[key] for key in sorted(remaining_keys)]
        filtered = filter_state_to_owned_projects(
            state,
            frozenset(remaining_keys),
            service_project_name=self._project_name_for_service,
        )
        filtered.metadata["project_names"] = remaining_names
        self._save_selected_stop_state(
            filtered,
            authoritative_project_names=remaining_names,
        )
        return True

    def _owned_project_names(self, state: RunState) -> dict[str, str]:
        projects: dict[str, str] = {}

        def add(raw_name: object) -> None:
            name = str(raw_name or "").strip()
            if name:
                projects.setdefault(name.casefold(), name)

        metadata_names = state.metadata.get("project_names")
        if isinstance(metadata_names, Iterable) and not isinstance(metadata_names, (str, bytes, Mapping)):
            for project in metadata_names:
                add(project)
        metadata_roots = state.metadata.get("project_roots")
        if isinstance(metadata_roots, Mapping):
            for project in metadata_roots:
                add(project)
        for project, requirements in state.requirements.items():
            add(getattr(requirements, "project", "") or project)
        for name, service in state.services.items():
            add(self._project_name_for_service(name, service))
        if state.mode == "trees" and any(project != "main" for project in projects):
            projects.pop("main", None)
        return projects

    def _active_project_keys(self, state: RunState) -> set[str]:
        active = {
            self._project_name_for_service(name, service)
            for name, service in state.services.items()
            if self._project_name_for_service(name, service)
        }
        active.update(
            self._requirement_project_key(project, requirements) for project, requirements in state.requirements.items()
        )
        raw_stopped = state.metadata.get("dashboard_stopped_services")
        if isinstance(raw_stopped, list):
            active.update(
                str(item.get("project", "")).strip().casefold()
                for item in raw_stopped
                if isinstance(item, Mapping) and str(item.get("project", "")).strip()
            )
        return {project for project in active if project}

    def _targeted_projects_have_no_managed_resources(
        self,
        state: RunState,
        targeted_project_keys: frozenset[str],
    ) -> bool:
        if any(
            self._project_name_for_service(name, service) in targeted_project_keys
            for name, service in state.services.items()
        ):
            return False
        return not any(
            self._requirement_project_key(project, requirements) in targeted_project_keys
            and cast(Any, self)._requirements_have_enabled_components(requirements)
            for project, requirements in state.requirements.items()
        )

    def _remove_targeted_requirements(
        self,
        state: RunState,
        targeted_project_keys: frozenset[str],
    ) -> None:
        owner = cast(Any, self)
        for project, requirements in list(state.requirements.items()):
            if self._requirement_project_key(project, requirements) not in targeted_project_keys:
                continue
            owner._release_requirement_ports(requirements)
            state.requirements.pop(project, None)

    @staticmethod
    def _requirement_project_key(project: str, requirements: RequirementsResult) -> str:
        return str(getattr(requirements, "project", "") or project).strip().casefold()
