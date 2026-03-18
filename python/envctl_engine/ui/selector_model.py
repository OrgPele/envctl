from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence


SelectorKind = str


@dataclass(frozen=True, slots=True)
class SelectorItem:
    id: str
    label: str
    kind: SelectorKind
    token: str
    scope_signature: tuple[str, ...]
    enabled: bool = True
    section: str = ""


@dataclass(frozen=True, slots=True)
class SuppressedSelectorItem:
    id: str
    label: str
    reason: str


@dataclass(frozen=True, slots=True)
class SelectorBuildResult:
    items: list[SelectorItem]
    suppressed: list[SuppressedSelectorItem] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SelectorContext:
    projects: Sequence[object]
    services: Sequence[str] = ()
    allow_all: bool = False
    allow_untested: bool = False
    untested_projects: Sequence[str] = ()
    mode: str = "project"


def build_project_selector_items(context: SelectorContext) -> SelectorBuildResult:
    project_names = _project_names(context.projects)
    concrete: list[SelectorItem] = []
    for name in project_names:
        concrete.append(
            SelectorItem(
                id=f"project:{name}",
                label=name,
                kind="project",
                token=f"__PROJECT__:{name}",
                scope_signature=(f"project:{name}",),
                section="Projects",
            )
        )

    synthetic: list[SelectorItem] = []
    if context.allow_untested:
        untested = [name for name in context.untested_projects if name in project_names]
        if 0 < len(untested) < len(project_names):
            synthetic.append(
                SelectorItem(
                    id="synthetic:untested",
                    label="Run untested projects",
                    kind="synthetic_untested",
                    token="__UNTESTED__",
                    scope_signature=tuple(sorted(f"project:{name}" for name in untested)),
                    section="Shortcuts",
                )
            )
    return _dedupe_and_filter([*concrete, *synthetic])


def build_grouped_selector_items(context: SelectorContext) -> SelectorBuildResult:
    project_names = _project_names(context.projects)
    services = [service.strip() for service in context.services if str(service).strip()]

    concrete_services: list[SelectorItem] = []
    for service in services:
        service_label = _format_grouped_service_label(service)
        concrete_services.append(
            SelectorItem(
                id=f"service:{service}",
                label=service_label,
                kind="service",
                token=service,
                scope_signature=(f"service:{service}",),
                section="Services",
            )
        )

    project_groups: list[SelectorItem] = []
    for name in project_names:
        scoped = tuple(sorted(f"service:{service}" for service in services if service.startswith(f"{name} ")))
        if not scoped:
            # No concrete services for this project; fallback to explicit project scope.
            scoped = (f"project:{name}",)
        project_groups.append(
            SelectorItem(
                id=f"project_group:{name}",
                label=f"{name} - ALL",
                kind="project_group",
                token=f"__PROJECT__:{name}",
                scope_signature=scoped,
                section="Projects",
            )
        )

    return _dedupe_and_filter([*concrete_services, *project_groups])


def _format_grouped_service_label(service: str) -> str:
    head, separator, tail = service.partition(" ")
    if separator and head and tail:
        return f"{head} - {tail}"
    return service


def _project_names(projects: Iterable[object]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for project in projects:
        name = str(getattr(project, "name", "")).strip()
        if not name:
            continue
        lowered = name.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        names.append(name)
    return names


def _dedupe_and_filter(items: Sequence[SelectorItem]) -> SelectorBuildResult:
    kept: list[SelectorItem] = []
    suppressed: list[SuppressedSelectorItem] = []
    seen_scopes: set[tuple[str, ...]] = set()
    for item in items:
        signature = tuple(sorted(scope for scope in item.scope_signature if scope))
        if not item.enabled:
            suppressed.append(SuppressedSelectorItem(id=item.id, label=item.label, reason="disabled"))
            continue
        if not signature:
            suppressed.append(SuppressedSelectorItem(id=item.id, label=item.label, reason="empty_scope"))
            continue
        if signature in seen_scopes:
            suppressed.append(SuppressedSelectorItem(id=item.id, label=item.label, reason="duplicate_scope"))
            continue
        seen_scopes.add(signature)
        kept.append(
            SelectorItem(
                id=item.id,
                label=item.label,
                kind=item.kind,
                token=item.token,
                scope_signature=signature,
                enabled=item.enabled,
                section=item.section,
            )
        )
    return SelectorBuildResult(items=kept, suppressed=suppressed)
