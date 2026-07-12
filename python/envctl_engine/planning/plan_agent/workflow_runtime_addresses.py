from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree
from envctl_engine.runtime.runtime_context import optional_state_repository
from envctl_engine.state.lookup import call_state_loader
from envctl_engine.state.models import RunState


@dataclass(frozen=True, slots=True)
class RuntimeAddressPromptBuilder:
    runtime: Any
    worktree: CreatedPlanWorktree | None = None

    def prompt_section(self) -> str:
        state = _latest_runtime_state(self.runtime, worktree=self.worktree)
        if state is None:
            return ""
        lines = [
            "## Current envctl runtime addresses",
            "Use these currently known localhost addresses when validating or debugging. "
            "They are generated from saved envctl runtime state; verify them again if you restart services.",
        ]
        dependency_lines = _dependency_address_lines(state, worktree=self.worktree)
        service_lines = _service_address_lines(state, worktree=self.worktree)
        if dependency_lines:
            lines.append("Dependencies:")
            lines.extend(f"- {line}" for line in dependency_lines)
        if service_lines:
            lines.append("Backend/frontend:")
            lines.extend(f"- {line}" for line in service_lines)
        if len(lines) == 2:
            return ""
        return "\n".join(lines)


def _append_runtime_addresses_for_preset(
    runtime: Any,
    *,
    preset: str,
    prompt_text: str,
    worktree: CreatedPlanWorktree | None = None,
) -> str:
    if str(preset).strip() != "implement_task":
        return prompt_text
    context = _runtime_addresses_prompt_section(runtime, worktree=worktree)
    if not context:
        return prompt_text
    return f"{prompt_text.rstrip()}\n\n{context}\n"


def _runtime_addresses_prompt_section(runtime: Any, *, worktree: CreatedPlanWorktree | None = None) -> str:
    return RuntimeAddressPromptBuilder(runtime, worktree=worktree).prompt_section()


def _latest_runtime_state(runtime: Any, *, worktree: CreatedPlanWorktree | None = None) -> RunState | None:
    project_names = [worktree.name] if worktree is not None and str(worktree.name).strip() else None
    state_repository = optional_state_repository(runtime)
    if state_repository is not None and hasattr(state_repository, "load_latest"):
        for selected_projects in _state_lookup_project_attempts(project_names):
            try:
                state = call_state_loader(
                    state_repository.load_latest,
                    project_names=selected_projects,
                )
            except Exception:
                state = None
            if isinstance(state, RunState):
                return state
    try_loader = getattr(runtime, "_try_load_existing_state", None)
    if callable(try_loader):
        for mode in ("trees", "main"):
            for selected_projects in _state_lookup_project_attempts(project_names):
                try:
                    state = call_state_loader(
                        try_loader,
                        mode=mode,
                        strict_mode_match=True,
                        project_names=selected_projects,
                    )
                except Exception:
                    state = None
                if isinstance(state, RunState):
                    return state
    return None


def _state_lookup_project_attempts(project_names: list[str] | None) -> tuple[list[str] | None, ...]:
    if project_names is None:
        return (None,)
    return (project_names, None)


def _dependency_address_lines(state: RunState, *, worktree: CreatedPlanWorktree | None = None) -> list[str]:
    rows: list[str] = []
    seen: set[tuple[str, int]] = set()
    for storage_key, requirements in state.requirements.items():
        project_name = str(getattr(requirements, "project", "") or storage_key).strip()
        if not _state_project_matches_worktree(project_name, worktree):
            continue
        for dependency_id in ("postgres", "redis", "supabase", "n8n"):
            component = requirements.component(dependency_id)
            if not bool(component.get("enabled", False)):
                continue
            port = _component_port(component)
            if port is None:
                continue
            key = (dependency_id, port)
            if key in seen:
                continue
            seen.add(key)
            address = _dependency_address(dependency_id, port)
            rows.append(f"{_dependency_label(dependency_id)} ({project_name}): {address}")
    return rows


def _service_address_lines(state: RunState, *, worktree: CreatedPlanWorktree | None = None) -> list[str]:
    rows: list[str] = []
    for service in state.services.values():
        if not _state_service_matches_worktree(service, worktree):
            continue
        service_type = str(service.type or "").strip().lower()
        if service_type not in {"backend", "frontend"}:
            continue
        port = service.actual_port or service.requested_port
        if port is None:
            continue
        label = "Backend" if service_type == "backend" else "Frontend"
        rows.append(f"{label} ({service.name}): http://localhost:{int(port)}")
    return rows


def _state_project_matches_worktree(project_name: object, worktree: CreatedPlanWorktree | None) -> bool:
    if worktree is None:
        return True
    normalized_project = str(project_name or "").strip().casefold()
    normalized_worktree = str(worktree.name or "").strip().casefold()
    if normalized_project == normalized_worktree:
        return True
    return bool(normalized_project and normalized_worktree.startswith(f"{normalized_project}-"))


def _state_service_matches_worktree(service: object, worktree: CreatedPlanWorktree | None) -> bool:
    if worktree is None:
        return True
    project = str(getattr(service, "project", "") or "").strip()
    if project and _state_project_matches_worktree(project, worktree):
        return True
    service_name = str(getattr(service, "name", "") or "").strip()
    worktree_name = str(worktree.name or "").strip()
    if worktree_name and service_name.casefold().startswith(f"{worktree_name.casefold()} "):
        return True
    cwd_raw = str(getattr(service, "cwd", "") or "").strip()
    if not cwd_raw:
        return False
    try:
        cwd = Path(cwd_raw).expanduser().resolve(strict=False)
        root = Path(worktree.root).expanduser().resolve(strict=False)
    except OSError:
        return False
    return cwd == root or root in cwd.parents


def _component_port(component: Mapping[str, object]) -> int | None:
    for key in ("final", "actual", "requested"):
        port = _int_or_none(component.get(key))
        if port is not None and port > 0:
            return port
    resources = component.get("resources")
    if isinstance(resources, Mapping):
        port = _int_or_none(resources.get("primary"))
        if port is not None and port > 0:
            return port
    return None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _dependency_label(dependency_id: str) -> str:
    return {"postgres": "Postgres", "redis": "Redis", "supabase": "Supabase", "n8n": "n8n"}.get(
        dependency_id,
        dependency_id,
    )


def _dependency_address(dependency_id: str, port: int) -> str:
    if dependency_id == "redis":
        return f"redis://localhost:{port}"
    if dependency_id in {"supabase", "n8n"}:
        return f"http://localhost:{port}"
    return f"localhost:{port}"


__all__ = tuple(name for name in globals() if not name.startswith("__"))
