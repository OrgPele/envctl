from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Mapping, cast

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime_action_support import (
    action_env as runtime_action_env,
    action_extra_env as runtime_action_extra_env,
    action_replacements as runtime_action_replacements,
    project_name_from_service as runtime_project_name_from_service,
    resolve_action_targets as runtime_resolve_action_targets,
    run_action_command as runtime_run_action_command,
    run_analyze_action as runtime_run_analyze_action,
    run_commit_action as runtime_run_commit_action,
    run_delete_worktree_action as runtime_run_delete_worktree_action,
    run_migrate_action as runtime_run_migrate_action,
    run_pr_action as runtime_run_pr_action,
    run_project_action as runtime_run_project_action,
    run_test_action as runtime_run_test_action,
    selectors_from_passthrough as runtime_selectors_from_passthrough,
)

if TYPE_CHECKING:
    from envctl_engine.runtime.engine_runtime import ProjectContext


class RuntimeActionFacadeMixin:
    def _run_action_command(self, route: Route) -> int:
        return runtime_run_action_command(self, route)

    def _resolve_action_targets(self, route: Route, *, trees_only: bool) -> tuple[list[ProjectContext], str | None]:
        targets, error = runtime_resolve_action_targets(self, route, trees_only=trees_only)
        return cast("list[ProjectContext]", targets), error

    @staticmethod
    def _selectors_from_passthrough(passthrough_args: Iterable[str]) -> set[str]:
        return runtime_selectors_from_passthrough(passthrough_args)

    @staticmethod
    def _project_name_from_service(service_name: str) -> str:
        return runtime_project_name_from_service(service_name)

    def _run_test_action(self, route: Route, targets: list[ProjectContext]) -> int:
        return runtime_run_test_action(self, route, targets)

    def _run_pr_action(self, route: Route, targets: list[ProjectContext]) -> int:
        return runtime_run_pr_action(self, route, targets)

    def _run_commit_action(self, route: Route, targets: list[ProjectContext]) -> int:
        return runtime_run_commit_action(self, route, targets)

    def _run_analyze_action(self, route: Route, targets: list[ProjectContext]) -> int:
        return runtime_run_analyze_action(self, route, targets)

    def _run_migrate_action(self, route: Route, targets: list[ProjectContext]) -> int:
        return runtime_run_migrate_action(self, route, targets)

    def _run_project_action(
        self,
        route: Route,
        targets: list[ProjectContext],
        *,
        command_name: str,
        env_key: str,
        default_command: list[str] | None,
        default_cwd: Path,
        default_append_project_path: bool,
        extra_env: Mapping[str, str],
    ) -> int:
        return runtime_run_project_action(
            self,
            route,
            targets,
            command_name=command_name,
            env_key=env_key,
            default_command=default_command,
            default_cwd=default_cwd,
            default_append_project_path=default_append_project_path,
            extra_env=extra_env,
        )

    def _run_delete_worktree_action(self, route: Route) -> int:
        return runtime_run_delete_worktree_action(self, route)

    def _action_replacements(
        self,
        targets: list[ProjectContext],
        *,
        target: ProjectContext | None,
    ) -> dict[str, str]:
        return runtime_action_replacements(self, targets, target=target)

    def _action_env(
        self,
        command_name: str,
        targets: list[ProjectContext],
        *,
        target: ProjectContext | None,
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        return runtime_action_env(
            self,
            command_name,
            targets,
            target=target,
            extra=extra,
        )

    @staticmethod
    def _action_extra_env(route: Route) -> dict[str, str]:
        return runtime_action_extra_env(route)
