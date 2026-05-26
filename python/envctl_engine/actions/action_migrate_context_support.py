from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from envctl_engine.state.models import PortPlan, RequirementsResult


@dataclass(frozen=True)
class MigrateProjectContext:
    name: str
    root: Path
    ports: dict[str, PortPlan]


def migrate_requirements_for_target(
    *,
    runtime: Any,
    route: object | None,
    project_name: str,
) -> RequirementsResult | None:
    route_mode = getattr(route, "mode", None)
    state = runtime.load_existing_state(mode=route_mode) if isinstance(route_mode, str) else None
    if state is None:
        return None
    requirements_map = getattr(state, "requirements", None)
    if not isinstance(requirements_map, dict):
        return None
    candidate = requirements_map.get(project_name)
    if isinstance(candidate, RequirementsResult):
        return candidate
    normalized_name = project_name.strip().lower()
    for key, value in requirements_map.items():
        if str(key).strip().lower() == normalized_name and isinstance(value, RequirementsResult):
            return value
    return None


def migrate_backend_cwd(target_root: Path) -> Path:
    backend_dir = target_root / "backend"
    if backend_dir.is_dir():
        return backend_dir
    return target_root


def migrate_project_context(
    *,
    project_name: str,
    project_root: Path,
    requirements: RequirementsResult,
) -> MigrateProjectContext:
    ports: dict[str, PortPlan] = {}
    for component_name, port_key in (
        ("postgres", "db"),
        ("redis", "redis"),
        ("n8n", "n8n"),
        ("supabase", "db"),
    ):
        if port_key in ports:
            continue
        component = requirements.component(component_name)
        port = migrate_component_port(component)
        if port <= 0:
            continue
        ports[port_key] = PortPlan(
            project=project_name,
            requested=port,
            assigned=port,
            final=port,
            source="requirements_state",
        )
    return MigrateProjectContext(name=project_name, root=project_root, ports=ports)


def migrate_component_port(component: Mapping[str, object]) -> int:
    for key in ("final", "requested", "assigned"):
        value = _positive_int(component.get(key))
        if value > 0:
            return value
    return 0


def _positive_int(raw: object) -> int:
    if raw is None or raw == "":
        return 0
    if isinstance(raw, bool):
        return int(raw)
    try:
        value = int(raw if isinstance(raw, (int, float, str)) else str(raw))
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0
