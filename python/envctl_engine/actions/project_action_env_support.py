from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping

from envctl_engine.actions.action_command_support import (
    build_action_env,
    build_action_extra_env,
    build_action_replacements,
)
from envctl_engine.actions.action_target_support import action_target_identity
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.runtime_context import resolve_state_repository


def action_replacements(
    *,
    runtime: Any,
    targets: list[object],
    target: object | None,
) -> dict[str, str]:
    return build_action_replacements(
        repo_root=runtime.config.base_dir,
        targets=targets,
        target=target,
    )


def action_env(
    *,
    runtime: Any,
    command_name: str,
    targets: list[object],
    route: Route | None,
    target: object | None,
    extra: Mapping[str, str] | None = None,
    process_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    route_mode = getattr(route, "mode", None)
    state = runtime.load_existing_state(mode=route_mode) if isinstance(route_mode, str) else None
    run_id = getattr(state, "run_id", None)
    state_repository = resolve_state_repository(runtime)
    tree_diffs_root = state_repository.tree_diffs_dir_path(run_id)  # type: ignore[attr-defined]
    return build_action_env(
        process_env=os.environ if process_env is None else process_env,
        runtime_env=runtime.env,
        repo_root=runtime.config.base_dir,
        runtime_root=state_repository.runtime_root,  # type: ignore[attr-defined]
        run_id=run_id,
        tree_diffs_root=tree_diffs_root,
        command_name=command_name,
        targets=targets,
        route=route,
        target=target,
        extra=extra,
    )


def action_extra_env(route: Route) -> dict[str, str]:
    return build_action_extra_env(route)


def test_action_extra_env(
    *,
    runtime: Any,
    route: Route | None,
    target: object | None,
    suite_source: str,
    project_context_builder: Callable[..., object],
) -> dict[str, str]:
    normalized_source = str(suite_source or "").strip().lower()
    if normalized_source not in {"backend_pytest", "root_unittest"}:
        return {}
    if target is None:
        return {}
    identity = action_target_identity(target)
    if identity is None:
        return {}
    state = runtime.load_existing_state(mode=getattr(route, "mode", None))
    if state is None:
        return {}
    requirements_map = getattr(state, "requirements", None)
    if not isinstance(requirements_map, dict):
        return {}
    requirements = requirements_map.get(identity.name)
    if requirements is None:
        return {}
    context = project_context_builder(
        project_name=identity.name,
        project_root=identity.root,
        requirements=requirements,
    )
    projector = getattr(runtime.raw_runtime, "_project_service_env", None)
    if not callable(projector):
        return {}
    projected = projector(context, requirements=requirements, route=route, service_name="backend")
    if not isinstance(projected, dict):
        return {}
    return {str(key): str(value) for key, value in projected.items() if isinstance(key, str) and value is not None}


def migrate_action_env(
    *,
    runtime: Any,
    targets: list[object],
    route: Route | None,
    target: object | None,
    migrate_env_contracts: dict[str, dict[str, object]],
    base_env_builder: Callable[..., dict[str, str]],
    backend_cwd: Callable[[Path], Path],
    requirements_for_target: Callable[..., object | None],
    project_context_builder: Callable[..., object],
    contract_context_builder: Callable[..., object],
    resolve_backend_env_contract: Callable[..., object],
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = base_env_builder(
        "migrate",
        targets,
        route=route,
        target=target,
        extra=extra,
    )
    if target is None:
        return env

    identity = action_target_identity(target)
    if identity is None:
        return env
    project_name = identity.name
    target_root = identity.root
    resolved_backend_cwd = backend_cwd(target_root)
    runtime_raw = runtime.raw_runtime
    context = contract_context_builder(project_name=project_name, target_root=target_root)

    projected_env: dict[str, str] = {}
    requirements = requirements_for_target(route=route, project_name=project_name)
    if requirements is not None:
        project_context = project_context_builder(
            project_name=project_name,
            project_root=target_root,
            requirements=requirements,
        )
        projector = getattr(runtime_raw, "_project_service_env_internal", None)
        if callable(projector):
            projected_candidate = projector(project_context, requirements=requirements, route=route)
            if isinstance(projected_candidate, dict):
                projected_env = {
                    str(key): str(value)
                    for key, value in projected_candidate.items()
                    if isinstance(key, str) and isinstance(value, str)
                }

    contract = resolve_backend_env_contract(
        runtime_raw,
        context=context,
        backend_cwd=resolved_backend_cwd,
        base_env=env,
        projected_env=projected_env,
    )
    migrate_env_contracts[project_name] = {
        "env_file_path": str(contract.env_file_path) if contract.env_file_path is not None else None,
        "env_file_source": contract.env_file_source,
        "override_requested": contract.override_requested,
        "override_resolution": contract.override_resolution,
        "override_authoritative": contract.override_authoritative,
        "scrubbed_keys": list(contract.scrubbed_keys),
        "projected_keys": list(contract.projected_keys),
    }
    return contract.env
