from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from envctl_engine.requirements.core import dependency_ids
from envctl_engine.requirements.external import dependency_external_mode
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState


@dataclass(frozen=True, slots=True)
class ProjectIdentity:
    name: str
    root: str | None


def build_startup_identity_metadata(
    runtime: Any,
    *,
    runtime_mode: str,
    project_contexts: list[object],
    base_metadata: Mapping[str, object] | None = None,
    route: Route | None = None,
) -> dict[str, object]:
    metadata = dict(base_metadata or {})
    roots_by_key: dict[str, tuple[str, str]] = {}
    existing_roots = metadata.get("project_roots")
    if isinstance(existing_roots, Mapping):
        for raw_name, raw_root in existing_roots.items():
            name = str(raw_name).strip()
            root = normalize_project_root(raw_root)
            if name and root:
                roots_by_key[name.casefold()] = (name, root)
    for context in project_contexts:
        name = str(getattr(context, "name", "")).strip()
        root = normalize_project_root(getattr(context, "root", None))
        if name and root:
            roots_by_key[name.casefold()] = (name, root)
    project_roots = {name: root for name, root in (roots_by_key[key] for key in sorted(roots_by_key))}
    identity_payload = _startup_identity_payload(
        runtime,
        runtime_mode=runtime_mode,
        project_contexts=project_contexts,
        route=route,
    )
    identity_payload["projects"] = [{"name": name, "root": root} for name, root in project_roots.items()]
    identity_payload.pop("fingerprint", None)
    identity_payload["fingerprint"] = hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    metadata["project_roots"] = project_roots
    metadata["startup_identity"] = identity_payload
    return metadata


def _startup_identity_mismatch(previous: Mapping[str, object], current: Mapping[str, object]) -> dict[str, object]:
    previous_fingerprint = str(previous.get("fingerprint", "")).strip()
    current_fingerprint = str(current.get("fingerprint", "")).strip()
    if previous_fingerprint and current_fingerprint and previous_fingerprint == current_fingerprint:
        return {}

    previous_payload = _startup_identity_comparison_payload(previous)
    current_payload = _startup_identity_comparison_payload(current)
    if previous_payload == current_payload:
        return {}

    changed_fields = [
        key
        for key in sorted(set(previous_payload) | set(current_payload))
        if previous_payload.get(key) != current_payload.get(key)
    ]
    return {"fields": changed_fields}


def _startup_identity_comparison_payload(identity: Mapping[str, object]) -> dict[str, object]:
    return {str(key): value for key, value in identity.items() if str(key) != "fingerprint"}


def project_identities_from_contexts(contexts: list[object]) -> list[ProjectIdentity]:
    identities: list[ProjectIdentity] = []
    for context in contexts:
        name = str(getattr(context, "name", "")).strip()
        if not name:
            continue
        identities.append(ProjectIdentity(name=name, root=normalize_project_root(getattr(context, "root", None))))
    return _sorted_identities(identities)


def project_identities_from_state(runtime: Any, state: RunState) -> list[ProjectIdentity]:
    metadata_roots = state.metadata.get("project_roots")
    roots = metadata_roots if isinstance(metadata_roots, dict) else {}
    names: dict[str, str | None] = {}
    for project_name, root_value in roots.items():
        normalized_name = str(project_name).strip()
        if not normalized_name:
            continue
        names[normalized_name] = normalize_project_root(root_value)
    for project_name in state.requirements:
        normalized_name = str(project_name).strip()
        if not normalized_name:
            continue
        names.setdefault(normalized_name, normalize_project_root(roots.get(normalized_name)))
    for service_name in state.services:
        project_name = runtime._project_name_from_service(service_name)
        normalized_name = str(project_name).strip()
        if not normalized_name:
            continue
        names.setdefault(normalized_name, normalize_project_root(roots.get(normalized_name)))
    return _sorted_identities(ProjectIdentity(name=name, root=root) for name, root in names.items())


def identities_to_payload(identities: list[ProjectIdentity]) -> list[dict[str, str | None]]:
    return [{"name": identity.name, "root": identity.root} for identity in identities]


def normalize_project_root(root: object) -> str | None:
    if root is None:
        return None
    raw = str(root).strip()
    if not raw:
        return None
    return str(Path(raw).expanduser().resolve(strict=False))


def _service_enabled_for_context(runtime: Any, runtime_mode: str, service: object, context: object) -> bool:
    enabled_for_project = getattr(service, "enabled_for_project_root", None)
    if callable(enabled_for_project):
        return bool(enabled_for_project(runtime_mode, getattr(context, "root", None)))
    enabled_for_mode = getattr(service, "enabled_for_mode", None)
    if callable(enabled_for_mode):
        return bool(enabled_for_mode(runtime_mode))
    return False


def _startup_service_payload(runtime: Any, runtime_mode: str, project_contexts: list[object]) -> dict[str, bool]:
    services = {
        "backend": _service_enabled(runtime, runtime_mode, "backend"),
        "frontend": _service_enabled(runtime, runtime_mode, "frontend"),
    }
    config = getattr(runtime, "config", None)
    for service in getattr(config, "additional_services", ()):
        name = str(getattr(service, "name", "") or "").strip()
        if not name:
            continue
        services[name] = any(
            _service_enabled_for_context(runtime, runtime_mode, service, context) for context in project_contexts
        )
    return services


def _startup_identity_payload(
    runtime: Any,
    *,
    runtime_mode: str,
    project_contexts: list[object],
    route: Route | None = None,
) -> dict[str, object]:
    startup_enabled = _startup_enabled(runtime, runtime_mode)
    services = _startup_service_payload(runtime, runtime_mode, project_contexts)
    dependencies = [
        dependency_id
        for dependency_id in sorted(dependency_ids())
        if _requirement_enabled(runtime, runtime_mode, dependency_id)
    ]
    if not startup_enabled:
        dependencies = []
    dependency_modes = {
        dependency_id: (
            "external"
            if dependency_external_mode(runtime, dependency_id, mode=runtime_mode, route=route)
            else "managed"
        )
        for dependency_id in dependencies
    }
    payload = {
        "mode": runtime_mode,
        "projects": identities_to_payload(project_identities_from_contexts(project_contexts)),
        "startup_enabled": startup_enabled,
        "services": services,
        "dependencies": dependencies,
        "dependency_modes": dependency_modes,
        "directories": {
            "backend": str(getattr(runtime.config, "backend_dir_name", "backend")),
            "frontend": str(getattr(runtime.config, "frontend_dir_name", "frontend")),
        },
    }
    payload["fingerprint"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return payload


def _sorted_identities(identities: list[ProjectIdentity] | Any) -> list[ProjectIdentity]:
    return sorted(
        list(identities),
        key=lambda item: (item.name.lower(), item.root or ""),
    )


def _identity_keys(identities: list[ProjectIdentity], *, weak: bool) -> set[tuple[str, str | None]]:
    if weak:
        return {(identity.name.lower(), None) for identity in identities}
    return {(identity.name.lower(), identity.root) for identity in identities}


def _root_mismatches(selected: list[ProjectIdentity], state: list[ProjectIdentity]) -> set[str]:
    state_by_name = {identity.name.lower(): identity for identity in state}
    mismatches: set[str] = set()
    for identity in selected:
        state_identity = state_by_name.get(identity.name.lower())
        if state_identity is None or identity.root is None or state_identity.root is None:
            continue
        if identity.root != state_identity.root:
            mismatches.add(identity.name)
    return mismatches


def _startup_enabled(runtime: Any, runtime_mode: str) -> bool:
    config = getattr(runtime, "config", None)
    startup_enabled_for_mode = getattr(config, "startup_enabled_for_mode", None)
    if callable(startup_enabled_for_mode):
        return bool(startup_enabled_for_mode(runtime_mode))
    return True


def _service_enabled(runtime: Any, runtime_mode: str, service_name: str) -> bool:
    config = getattr(runtime, "config", None)
    service_enabled_for_mode = getattr(config, "service_enabled_for_mode", None)
    if callable(service_enabled_for_mode):
        return bool(service_enabled_for_mode(runtime_mode, service_name))
    return True


def _requirement_enabled(runtime: Any, runtime_mode: str, requirement_name: str) -> bool:
    config = getattr(runtime, "config", None)
    requirement_enabled_for_mode = getattr(config, "requirement_enabled_for_mode", None)
    if callable(requirement_enabled_for_mode):
        return bool(requirement_enabled_for_mode(runtime_mode, requirement_name))
    return True


def _auto_resume_start_enabled(route: Route) -> bool:
    if route.command not in {"start", "plan"}:
        return False
    if bool(route.flags.get("no_resume")):
        return False
    if bool(route.flags.get("planning_prs")):
        return False
    if bool(route.flags.get("setup_worktree")) or bool(route.flags.get("setup_worktrees")):
        return False
    return True
