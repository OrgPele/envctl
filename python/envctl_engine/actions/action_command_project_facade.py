from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Callable, Mapping

from envctl_engine.actions.action_git_command_support import (
    run_commit_action_with_owner,
    run_pr_action_with_owner,
    run_review_action_with_owner,
    run_ship_action_with_owner,
)
from envctl_engine.actions.action_migrate_execution_support import run_migrate_action_with_owner
from envctl_engine.actions.action_migrate_support import (
    MigrateProjectContext as _MigrateProjectContext,
    migrate_backend_cwd as migrate_backend_cwd_impl,
    migrate_project_context as migrate_project_context_impl,
    migrate_requirements_for_target as migrate_requirements_for_target_impl,
)
from envctl_engine.actions.action_project_report_owner import (
    persist_project_action_result_with_owner,
    project_action_failure_handler as project_action_failure_handler_impl,
    project_action_success_handler as project_action_success_handler_impl,
)
from envctl_engine.actions.project_action_support import (
    action_env as action_env_impl,
    action_extra_env as action_extra_env_impl,
    action_replacements as action_replacements_impl,
    migrate_action_env as migrate_action_env_impl,
    run_project_action as run_project_action_impl,
)
from envctl_engine.actions.action_output_support import (
    action_colors_enabled as action_colors_enabled_impl,
    colorize_action_text as colorize_action_text_impl,
)
from envctl_engine.actions.action_target_support import ActionTargetContext, execute_targeted_action
from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.service_bootstrap_domain import _resolve_backend_env_contract
from envctl_engine.state.models import RequirementsResult


def _runtime(owner: Any) -> Any:
    return getattr(owner, "runtime")


def _compat_attr(name: str, fallback: Any) -> Any:
    module = sys.modules.get("envctl_engine.actions.action_command_orchestrator")
    if module is None:
        return fallback
    return getattr(module, name, fallback)


def _stdout_is_live_terminal() -> bool:
    import sys

    streams = [getattr(sys, "stdout", None), getattr(sys, "__stdout__", None)]
    for stream in streams:
        if stream is None:
            continue
        try:
            if bool(getattr(stream, "isatty", lambda: False)()):
                return True
        except Exception:
            continue
    return False


class ActionCommandProjectFacadeMixin:
    def run_pr_action(self, route: Route, targets: list[object]) -> int:
        return run_pr_action_with_owner(self, route, targets, extra_env=self.action_extra_env(route))

    def run_commit_action(self, route: Route, targets: list[object]) -> int:
        return run_commit_action_with_owner(self, route, targets, extra_env=self.action_extra_env(route))

    def run_ship_action(self, route: Route, targets: list[object]) -> int:
        return run_ship_action_with_owner(self, route, targets, extra_env=self.action_extra_env(route))

    def run_review_action(self, route: Route, targets: list[object]) -> int:
        return run_review_action_with_owner(self, route, targets, extra_env=self.action_extra_env(route))

    def run_migrate_action(self, route: Route, targets: list[object]) -> int:
        return _compat_attr("run_migrate_action_with_owner", run_migrate_action_with_owner)(
            self, route, targets, extra_env=self.action_extra_env(route)
        )

    def run_project_action(
        self,
        route: Route,
        targets: list[object],
        *,
        command_name: str,
        env_key: str,
        default_command: list[str] | None,
        default_cwd: Path,
        default_append_project_path: bool,
        extra_env: Mapping[str, str],
    ) -> int:
        interactive_command = bool(route.flags.get("interactive_command"))
        return run_project_action_impl(
            runtime=_runtime(self),
            route=route,
            targets=targets,
            command_name=command_name,
            env_key=env_key,
            default_command=default_command,
            default_cwd=default_cwd,
            default_append_project_path=default_append_project_path,
            extra_env=extra_env,
            action_replacements_builder=self.action_replacements,
            action_env_builder=self.action_env,
            emit_status=getattr(self, "_emit_status"),
            success_handler=self._project_action_success_handler(command_name, route.mode, interactive_command),
            failure_handler=self._project_action_failure_handler(command_name, route.mode),
            stdout_is_live_terminal=_compat_attr("_stdout_is_live_terminal", _stdout_is_live_terminal),
            execute_targeted_action_fn=execute_targeted_action,
        )

    def action_replacements(
        self,
        targets: list[object],
        *,
        target: object | None,
    ) -> dict[str, str]:
        return action_replacements_impl(
            runtime=_runtime(self),
            targets=targets,
            target=target,
        )

    def action_env(
        self,
        command_name: str,
        targets: list[object],
        *,
        route: Route | None = None,
        target: object | None,
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        return action_env_impl(
            runtime=_runtime(self),
            command_name=command_name,
            targets=targets,
            route=route,
            target=target,
            extra=extra,
        )

    @staticmethod
    def action_extra_env(route: Route) -> dict[str, str]:
        return action_extra_env_impl(route)

    def migrate_action_env(
        self,
        *,
        targets: list[object],
        route: Route | None,
        target: object | None,
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        return migrate_action_env_impl(
            runtime=_runtime(self),
            targets=targets,
            route=route,
            target=target,
            extra=extra,
            migrate_env_contracts=getattr(self, "_migrate_env_contracts"),
            base_env_builder=self.action_env,
            backend_cwd=self._migrate_backend_cwd,
            requirements_for_target=self._migrate_requirements_for_target,
            project_context_builder=self._migrate_project_context,
            contract_context_builder=lambda project_name, target_root: _MigrateProjectContext(
                name=project_name,
                root=target_root,
                ports={},
            ),
            resolve_backend_env_contract=_resolve_backend_env_contract,
        )

    @staticmethod
    def _migrate_backend_cwd(target_root: Path) -> Path:
        return migrate_backend_cwd_impl(target_root)

    def _migrate_requirements_for_target(
        self,
        *,
        route: Route | None,
        project_name: str,
    ) -> RequirementsResult | None:
        return migrate_requirements_for_target_impl(runtime=_runtime(self), route=route, project_name=project_name)

    @staticmethod
    def _migrate_project_context(
        *,
        project_name: str,
        project_root: Path,
        requirements: RequirementsResult,
    ) -> _MigrateProjectContext:
        return migrate_project_context_impl(
            project_name=project_name,
            project_root=project_root,
            requirements=requirements,
        )

    def _project_action_success_handler(
        self,
        command_name: str,
        mode: str,
        interactive_command: bool,
    ) -> Callable[[ActionTargetContext, Any], None] | None:
        return project_action_success_handler_impl(self, command_name, mode, interactive_command)

    def _project_action_failure_handler(
        self,
        command_name: str,
        mode: str,
    ) -> Callable[[ActionTargetContext, str], None]:
        return project_action_failure_handler_impl(self, command_name, mode)

    def _persist_project_action_result(
        self,
        *,
        command_name: str,
        mode: str,
        project_name: str,
        status: str,
        error_output: str,
        extra_entry: Mapping[str, object] | None = None,
    ) -> None:
        persist_project_action_result_with_owner(
            self,
            command_name=command_name,
            mode=mode,
            project_name=project_name,
            status=status,
            error_output=error_output,
            extra_entry=extra_entry,
        )

    def _colors_enabled(self) -> bool:
        return action_colors_enabled_impl(_runtime(self))

    def _colorize(self, text: str, *, fg: str | None = None, bold: bool = False, dim: bool = False) -> str:
        return colorize_action_text_impl(
            text,
            enabled=self._colors_enabled(),
            fg=fg,
            bold=bold,
            dim=dim,
        )
