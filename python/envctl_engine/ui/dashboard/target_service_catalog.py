from __future__ import annotations

from typing import Any

from envctl_engine.dashboard_metadata import normalize_dashboard_service_types
from envctl_engine.shared.services import (
    project_name_from_service_name,
    service_display_name,
    service_project_name,
    service_slug_from_record,
)
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard.restart_selection_support import (
    dashboard_configured_missing_services_by_project,
    dashboard_project_configured_services,
)


class DashboardServiceCatalog:
    def __init__(self, state: RunState, runtime: Any, *, project_names: list[str]) -> None:
        self.state = state
        self.runtime = runtime
        self.requested_projects = {name.casefold() for name in project_names}

    def available_service_types(self) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for service_name, service in self.state.services.items():
            project_name = self._project_name_for_service(service_name, service)
            if not self._includes_project(project_name):
                continue
            service_type = service_slug_from_record(service) if service is not None else ""
            self._append_once(ordered, seen, service_type)

        for project_name, service_types in dashboard_project_configured_services(self.state).items():
            if not self._includes_project(project_name):
                continue
            for service_type in sorted(service_types):
                self._append_once(ordered, seen, service_type)

        if ordered:
            return ordered
        for service_type in normalize_dashboard_service_types(
            self.state.metadata.get("dashboard_configured_service_types")
        ):
            self._append_once(ordered, seen, service_type)
        return ordered

    def service_names_for_types(self, service_types: list[str]) -> list[str]:
        requested_types = {name.casefold() for name in service_types}
        selected: list[str] = []
        seen_names: set[str] = set()
        for service_name, service in self.state.services.items():
            project_name = self._project_name_for_service(service_name, service)
            if not self._includes_project(project_name):
                continue
            service_type = service_slug_from_record(service) if service is not None else ""
            if service_type and service_type.casefold() in requested_types:
                selected.append(service_name)
                seen_names.add(str(service_name))

        for project_name, missing_service_types in dashboard_configured_missing_services_by_project(self.state).items():
            if not self._includes_project(project_name):
                continue
            for service_type in sorted(missing_service_types):
                if service_type.casefold() not in requested_types:
                    continue
                service_name = f"{project_name} {service_display_name(service_type)}"
                if service_name in seen_names:
                    continue
                selected.append(service_name)
                seen_names.add(service_name)
        return selected

    def _project_name_for_service(self, service_name: str, service: object) -> str:
        project_name = service_project_name(service)
        if not project_name:
            project_name = str(self.runtime._project_name_from_service(service_name) or "").strip()
        if not project_name:
            project_name = str(project_name_from_service_name(str(service_name))).strip()
        return project_name

    def _includes_project(self, project_name: str) -> bool:
        return not self.requested_projects or project_name.casefold() in self.requested_projects

    @staticmethod
    def _append_once(ordered: list[str], seen: set[str], value: str) -> None:
        if not value or value in seen:
            return
        seen.add(value)
        ordered.append(value)


__all__ = ("DashboardServiceCatalog",)
