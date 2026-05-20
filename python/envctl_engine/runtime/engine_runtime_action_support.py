from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from envctl_engine.actions.action_command_orchestrator import ActionCommandOrchestrator
from envctl_engine.runtime.command_router import Route


def run_action_command(runtime: Any, route: object) -> int:
    return runtime.action_command_orchestrator.execute(route)


def resolve_action_targets(runtime: Any, route: object, *, trees_only: bool) -> tuple[list[object], str | None]:
    return runtime.action_command_orchestrator.resolve_targets(route, trees_only=trees_only)


def selectors_from_passthrough(passthrough_args: Iterable[str]) -> set[str]:
    selectors: set[str] = set()
    for token in passthrough_args:
        if token.startswith("-"):
            continue
        parts = [part.strip().lower() for part in token.split(",")]
        selectors.update(part for part in parts if part)
    return selectors


def projects_for_services(runtime: Any, service_targets: list[object]) -> list[str]:
    return runtime.action_command_orchestrator.projects_for_services(service_targets)


def project_name_from_service(service_name: str) -> str:
    text = service_name.strip()
    lowered = text.lower()
    if lowered.endswith(" backend"):
        return text[:-8].strip()
    if lowered.endswith(" frontend"):
        return text[:-9].strip()
    return ""


def run_test_action(runtime: Any, route: object, targets: list[object]) -> int:
    return runtime.action_command_orchestrator.run_test_action(route, targets)


def run_pr_action(runtime: Any, route: object, targets: list[object]) -> int:
    return runtime.action_command_orchestrator.run_pr_action(route, targets)


def run_commit_action(runtime: Any, route: object, targets: list[object]) -> int:
    return runtime.action_command_orchestrator.run_commit_action(route, targets)


def run_analyze_action(runtime: Any, route: object, targets: list[object]) -> int:
    return runtime.action_command_orchestrator.run_review_action(route, targets)


def run_migrate_action(runtime: Any, route: object, targets: list[object]) -> int:
    return runtime.action_command_orchestrator.run_migrate_action(route, targets)


def run_project_action(
    runtime: Any,
    route: object,
    targets: list[object],
    *,
    command_name: str,
    env_key: str,
    default_command: list[str] | None,
    default_cwd: Path,
    default_append_project_path: bool,
    extra_env: Mapping[str, str],
) -> int:
    return runtime.action_command_orchestrator.run_project_action(
        route,
        targets,
        command_name=command_name,
        env_key=env_key,
        default_command=default_command,
        default_cwd=default_cwd,
        default_append_project_path=default_append_project_path,
        extra_env=extra_env,
    )


def run_delete_worktree_action(runtime: Any, route: object) -> int:
    return runtime.action_command_orchestrator.run_delete_worktree_action(route)


def action_replacements(runtime: Any, targets: list[object], *, target: object | None) -> dict[str, str]:
    return runtime.action_command_orchestrator.action_replacements(targets, target=target)


def action_env(
    runtime: Any,
    command_name: str,
    targets: list[object],
    *,
    target: object | None,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    return runtime.action_command_orchestrator.action_env(
        command_name,
        targets,
        target=target,
        extra=extra,
    )


def action_extra_env(route: Route) -> dict[str, str]:
    return ActionCommandOrchestrator.action_extra_env(route)
