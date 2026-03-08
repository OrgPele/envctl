from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI
from envctl_engine.ui.selection_types import TargetSelection


@dataclass(frozen=True, slots=True)
class SimpleProject:
    name: str


def interactive_selection_allowed(
    runtime: Any,
    route: Route,
    *,
    allow_dashboard_override: bool = False,
) -> bool:
    if allow_dashboard_override and bool(route.flags.get("interactive_command")):
        return True
    if not RuntimeTerminalUI._can_interactive_tty():
        return False
    batch_requested = False
    if hasattr(runtime, "_batch_mode_requested"):
        batch_requested = bool(runtime._batch_mode_requested(route))  # type: ignore[attr-defined]
    if batch_requested and not bool(route.flags.get("interactive_command")):
        return False
    return True


def project_names_from_state(runtime: Any, state: RunState) -> list[object]:
    names: list[str] = []
    seen: set[str] = set()
    for name in state.services:
        project = runtime._project_name_from_service(name)  # type: ignore[attr-defined]
        if not project:
            continue
        lowered = project.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        names.append(project)
    return [SimpleProject(name) for name in names]


def services_from_selection(runtime: Any, selection: TargetSelection, state: RunState) -> set[str]:
    if selection.all_selected:
        return set(state.services.keys())
    if selection.service_names:
        return {name for name in state.services if name in selection.service_names}
    if selection.project_names:
        selected: set[str] = set()
        for name in state.services:
            project = runtime._project_name_from_service(name)  # type: ignore[attr-defined]
            if not project:
                continue
            for wanted in selection.project_names:
                if project.lower() == wanted.lower():
                    selected.add(name)
                    break
        return selected
    return set()


def no_target_selected_message(
    command: str,
    *,
    route: Route | None,
    interactive_allowed: bool,
) -> str:
    label_map = {
        "logs": "log",
        "clear-logs": "log",
        "pr": "PR",
        "analyze": "analysis",
        "migrate": "migration",
        "blast-worktree": "worktree",
    }
    label = label_map.get(str(command).strip().lower(), str(command).strip().lower())
    if interactive_allowed or route is None:
        return f"No {label} target selected."
    mode = str(route.mode).strip().lower()
    discovery = "envctl --list-trees --json" if mode == "trees" else "envctl --list-targets --main --json"
    return (
        f"No {label} target selected. "
        f"In headless mode, run '{discovery}' and retry with '--project <name>', '--service <name>', or '--all'."
    )


def route_has_explicit_target(route: Route, runtime: Any) -> bool:
    if bool(route.flags.get("all")):
        return True
    if route.projects:
        return True
    services = route.flags.get("services")
    if isinstance(services, list) and any(str(item).strip() for item in services):
        return True
    selectors_from_passthrough = getattr(runtime, "_selectors_from_passthrough", None)
    if callable(selectors_from_passthrough):
        selectors = selectors_from_passthrough(route.passthrough_args)
        if isinstance(selectors, set) and selectors:
            return True
    return False


def service_types_from_service_names(service_names: Sequence[str]) -> set[str]:
    types: set[str] = set()
    for name in service_names:
        normalized = str(name).strip().lower()
        if normalized.endswith(" backend") or normalized == "backend":
            types.add("backend")
        elif normalized.endswith(" frontend") or normalized == "frontend":
            types.add("frontend")
    return types
