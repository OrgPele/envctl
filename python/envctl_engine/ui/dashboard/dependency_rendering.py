from __future__ import annotations

from typing import Any, Callable

from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.state.models import RequirementsResult, RunState
from envctl_engine.ui.status_symbols import dependency_status_badge


VisualUrlFn = Callable[[Any, int], str]
SeverityColorFn = Callable[[str], str]


def print_dashboard_dependency_rows(
    self: Any,
    *,
    state: RunState,
    project: str,
    ok_color: str,
    warn_color: str,
    bad_color: str,
    label_color: str,
    reset: str,
    visual_url_fn: VisualUrlFn,
    severity_color_fn: SeverityColorFn,
) -> None:
    _ = label_color
    project_key = str(project).strip().casefold()
    matching_requirements = [
        requirements
        for storage_key, requirements in state.requirements.items()
        if str(getattr(requirements, "project", "") or storage_key).strip().casefold() == project_key
    ]
    for requirements in matching_requirements:
        print_dashboard_requirement_component_rows(
            self,
            requirements=requirements,
            ok_color=ok_color,
            warn_color=warn_color,
            bad_color=bad_color,
            reset=reset,
            visual_url_fn=visual_url_fn,
            severity_color_fn=severity_color_fn,
        )


def print_dashboard_shared_dependency_rows(
    self: Any,
    *,
    state: RunState,
    ok_color: str,
    warn_color: str,
    bad_color: str,
    label_color: str,
    reset: str,
    visual_url_fn: VisualUrlFn,
    severity_color_fn: SeverityColorFn,
) -> None:
    requirements = dashboard_shared_dependency_requirements(state)
    if requirements is None or not requirements_has_dashboard_dependencies(requirements):
        return
    print(f"  {label_color}Shared dependencies:{reset}")
    print_dashboard_requirement_component_rows(
        self,
        requirements=requirements,
        ok_color=ok_color,
        warn_color=warn_color,
        bad_color=bad_color,
        reset=reset,
        visual_url_fn=visual_url_fn,
        severity_color_fn=severity_color_fn,
    )
    print("")


def print_dashboard_requirement_component_rows(
    self: Any,
    *,
    requirements: RequirementsResult,
    ok_color: str,
    warn_color: str,
    bad_color: str,
    reset: str,
    visual_url_fn: VisualUrlFn,
    severity_color_fn: SeverityColorFn,
) -> None:
    _ = ok_color, warn_color, bad_color
    for definition in dependency_definitions():
        line = dashboard_dependency_line(
            self,
            requirements=requirements,
            dependency_id=definition.id,
            display_name=definition.display_name,
            reset=reset,
            visual_url_fn=visual_url_fn,
            severity_color_fn=severity_color_fn,
        )
        if line is None:
            continue
        print(line)


def dashboard_dependency_line(
    self: Any,
    *,
    requirements: RequirementsResult,
    dependency_id: str,
    display_name: str,
    reset: str,
    visual_url_fn: VisualUrlFn,
    severity_color_fn: SeverityColorFn,
) -> str | None:
    component = requirements.component(dependency_id)
    if not bool(component.get("enabled", False)) or dependency_id == "postgres":
        return None
    port = component.get("final") or component.get("requested")
    runtime_status = str(component.get("runtime_status", "")).strip().lower()
    badge = dependency_status_badge(
        runtime_status,
        success=bool(component.get("success", False)),
        simulated=bool(component.get("simulated", False)),
        failure_count=len(requirements.failures or []),
    )
    color = severity_color_fn(badge.severity)
    external_url = str(component.get("external_url") or "").strip()
    if badge.severity == "failure":
        url = external_url or "n/a"
    elif external_url:
        url = external_url
    else:
        url = visual_url_fn(self, port) if isinstance(port, int) and port > 0 else "n/a"
    label = f"External {badge.label}" if bool(component.get("external", False)) else badge.label
    return f"    {color}{badge.symbol}{reset} {display_name}: {url} [{label}]"


def dashboard_dependency_scope(state: RunState) -> str:
    raw = state.metadata.get("dashboard_dependency_scope")
    if isinstance(raw, str) and raw.strip().lower() in {"shared", "isolated", "none"}:
        return raw.strip().lower()
    if dashboard_legacy_tree_requirements_are_shared(state):
        return "shared"
    return "isolated"


def dashboard_legacy_tree_requirements_are_shared(state: RunState) -> bool:
    if state.mode != "trees":
        return False
    dependency_projects: set[str] = set()
    dependency_keys: set[str] = set()
    dependency_signatures: set[tuple[tuple[str, tuple[tuple[str, object], ...]], ...]] = set()
    for key, requirements in state.requirements.items():
        if not isinstance(requirements, RequirementsResult):
            continue
        if not requirements_has_dashboard_dependencies(requirements):
            continue
        requirement_project = str(getattr(requirements, "project", "") or "").strip()
        if requirement_project:
            dependency_projects.add(requirement_project)
        dependency_signatures.add(dashboard_dependency_signature(requirements))
        dependency_keys.add(str(key).strip())
    if len(dependency_keys) < 2:
        return False
    if not dependency_projects:
        return len(dependency_signatures) == 1
    if len(dependency_projects) != 1:
        return False
    shared_project = next(iter(dependency_projects))
    return bool(dependency_keys) and all(key != shared_project for key in dependency_keys)


def dashboard_dependency_signature(
    requirements: RequirementsResult,
) -> tuple[tuple[str, tuple[tuple[str, object], ...]], ...]:
    signature: list[tuple[str, tuple[tuple[str, object], ...]]] = []
    for definition in dependency_definitions():
        if definition.id == "postgres":
            continue
        component = requirements.component(definition.id)
        if not bool(component.get("enabled", False)):
            continue
        component_signature = tuple(
            (field, component.get(field))
            for field in (
                "enabled",
                "requested",
                "final",
                "runtime_status",
                "success",
                "simulated",
                "container_name",
            )
        )
        signature.append((definition.id, component_signature))
    return tuple(signature)


def dashboard_shared_dependency_requirements(state: RunState) -> RequirementsResult | None:
    project_raw = state.metadata.get("dashboard_shared_dependency_project")
    project = str(project_raw or "").strip() if isinstance(project_raw, str) else ""
    if project:
        direct = state.requirements.get(project)
        if isinstance(direct, RequirementsResult):
            return direct
        for requirements in state.requirements.values():
            if str(getattr(requirements, "project", "") or "").strip() == project:
                return requirements
    main = state.requirements.get("Main")
    if isinstance(main, RequirementsResult):
        return main
    for requirements in state.requirements.values():
        if requirements_has_dashboard_dependencies(requirements):
            return requirements
    return None


def requirements_has_dashboard_dependencies(requirements: RequirementsResult) -> bool:
    for definition in dependency_definitions():
        if definition.id == "postgres":
            continue
        if bool(requirements.component(definition.id).get("enabled", False)):
            return True
    return False
