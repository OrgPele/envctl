from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from envctl_engine.dashboard_metadata import (
    DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY,
    dashboard_configured_missing_services_by_project,
)
from envctl_engine.state.models import RunState
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.ui.dashboard import dependency_rendering
from envctl_engine.ui.dashboard import service_rendering
from envctl_engine.ui.status_symbols import service_status_badge


@dataclass(frozen=True)
class DashboardSnapshotModel:
    """State projection and service accounting for one terminal dashboard render."""

    failing_services: list[str]
    projection: dict[str, object]
    ordered_projects: list[str]
    stopped_services: dict[str, dict[str, str]]
    project_configured_services: dict[str, set[str]]
    configured_missing_services: dict[str, set[str]]
    configured_service_types: set[str]
    configured_service_total: int
    runs_disabled_dashboard: bool
    stopped_service_count: int
    total_services: int
    running_services: int
    issue_services: int
    starting_services: int
    shared_dependency_grouping: bool


def build_dashboard_snapshot_model(
    state: RunState,
    *,
    visual_host: str,
    reconcile_fn: Callable[[RunState], list[str]],
    emit_fn: Callable[..., object],
) -> DashboardSnapshotModel:
    failing_services = list(reconcile_fn(state))
    emit_fn(
        "state.reconcile",
        run_id=state.run_id,
        source="dashboard.snapshot",
        missing_count=len(failing_services),
        missing_services=failing_services,
    )
    projection = _dashboard_projection(state, visual_host=visual_host)
    stopped_services = service_rendering.dashboard_stopped_services_by_project(state)
    project_configured_services = service_rendering.dashboard_project_configured_services(state)
    configured_missing_services = dashboard_configured_missing_services_by_project(
        configured_services=project_configured_services,
        stopped_services=stopped_services,
        active_service_names=set(state.services),
    )
    if stopped_services or project_configured_services:
        projection = dict(projection)
        for project in stopped_services:
            projection.setdefault(project, {})
        for project in project_configured_services:
            projection.setdefault(project, {})
    configured_service_types = service_rendering.dashboard_configured_service_types(state)
    configured_service_total = service_rendering.dashboard_configured_service_total(
        projection=projection,
        configured_service_types=configured_service_types,
    )
    runs_disabled_dashboard = service_rendering.dashboard_runs_disabled(state)
    stopped_service_count = service_rendering.dashboard_visible_stopped_service_count(
        state,
        stopped_services=stopped_services,
        configured_missing_services=configured_missing_services,
    )
    if configured_missing_services:
        emit_fn(
            "dashboard.configured_missing_services",
            run_id=state.run_id,
            services={project: sorted(service_types) for project, service_types in configured_missing_services.items()},
            metadata_key=DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY,
        )
    service_statuses = [
        str(getattr(service, "status", "unknown") or "unknown").strip().lower() for service in state.services.values()
    ]
    return DashboardSnapshotModel(
        failing_services=failing_services,
        projection=projection,
        ordered_projects=sorted(projection),
        stopped_services=stopped_services,
        project_configured_services=project_configured_services,
        configured_missing_services=configured_missing_services,
        configured_service_types=configured_service_types,
        configured_service_total=configured_service_total,
        runs_disabled_dashboard=runs_disabled_dashboard,
        stopped_service_count=stopped_service_count,
        total_services=len(service_statuses) + stopped_service_count,
        running_services=sum(1 for status in service_statuses if status in {"running", "healthy"}),
        issue_services=sum(1 for status in service_statuses if service_status_badge(status).severity == "failure"),
        starting_services=sum(1 for status in service_statuses if service_status_badge(status).severity == "warning"),
        shared_dependency_grouping=dependency_rendering.dashboard_dependency_scope(state) == "shared",
    )


def _dashboard_projection(state: RunState, *, visual_host: str) -> dict[str, object]:
    runtime_map = build_runtime_map(state, host=visual_host)
    projection = runtime_map.get("projection", {})
    if isinstance(projection, dict) and projection:
        return dict(projection)
    metadata_roots = state.metadata.get("project_roots")
    if isinstance(metadata_roots, Mapping):
        return {str(project).strip(): {} for project in metadata_roots if str(project).strip()}
    return {}
