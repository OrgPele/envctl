from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping

from envctl_engine.actions.action_target_support import ActionCommandResolution
from envctl_engine.actions.project_action_report_support import ship_action_status_message
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.runtime_context import resolve_process_runtime


class ProjectActionRunner:
    def __init__(
        self,
        *,
        runtime: Any,
        route: Route,
        targets: list[object],
        command_name: str,
        env_key: str,
        default_command: list[str] | None,
        default_cwd: Path,
        default_append_project_path: bool,
        extra_env: Mapping[str, str],
        action_replacements_builder: Callable[..., dict[str, str]],
        action_env_builder: Callable[..., dict[str, str]],
        emit_status: Callable[[str], None],
        success_handler: Callable[..., object] | None,
        failure_handler: Callable[..., object] | None,
        stdout_is_live_terminal: Callable[[], bool],
        execute_targeted_action_fn: Callable[..., int],
    ) -> None:
        self.runtime = runtime
        self.route = route
        self.targets = targets
        self.command_name = command_name
        self.env_key = env_key
        self.default_command = default_command
        self.default_cwd = default_cwd
        self.default_append_project_path = default_append_project_path
        self.extra_env = extra_env
        self.action_replacements_builder = action_replacements_builder
        self.action_env_builder = action_env_builder
        self.emit_status = emit_status
        self.success_handler = success_handler
        self.failure_handler = failure_handler
        self.stdout_is_live_terminal = stdout_is_live_terminal
        self.execute_targeted_action_fn = execute_targeted_action_fn

        self.raw_command = runtime.env.get(env_key)
        self.interactive_command = bool(route.flags.get("interactive_command"))
        self.process_runtime: Any | None = None
        self.stream_review_output = False
        self.command_extra_env = dict(extra_env)

    def run(self) -> int:
        if self.raw_command is None and self.default_command is None:
            print(f"No {self.command_name} command configured. Set {self.env_key} or add repo utility script.")
            return 1

        self.process_runtime = resolve_process_runtime(self.runtime)
        self.stream_review_output = self._should_stream_review_output()
        self.command_extra_env = self._command_extra_env()

        return self.execute_targeted_action_fn(
            targets=self.targets,
            command_name=self.command_name,
            interactive_command=self.interactive_command,
            resolve_command=self.resolve_command,
            build_env=self.build_env,
            process_run=self.process_run,
            emit_status=self.emit_status,
            interactive_print_failures=(not self.interactive_command) or self.command_name in {"pr", "review"},
            emit_success_output=not self.stream_review_output,
            on_success=self.success_handler,
            on_failure=self.failure_handler,
            success_print_formatter=self.success_print_message if self.command_name == "ship" else None,
            success_status_formatter=self.success_status_message if self.command_name == "ship" else None,
        )

    def resolve_command(self, context: object) -> ActionCommandResolution:
        target = getattr(context, "target_obj")
        target_root = Path(str(getattr(context, "root")))
        replacements = self.action_replacements_builder(self.targets, target=target)
        if self.raw_command is not None:
            try:
                command = self.runtime.split_command(self.raw_command, replacements=replacements)
            except RuntimeError as exc:
                return ActionCommandResolution(command=None, cwd=None, error=str(exc))
            return ActionCommandResolution(command=command, cwd=target_root)

        command: list[str] = []
        for token in list(self.default_command or []):
            value = str(token)
            for key, replacement in replacements.items():
                value = value.replace(f"{{{key}}}", replacement)
            command.append(value)
        if self.default_append_project_path:
            command.append(str(target_root))
        return ActionCommandResolution(command=command, cwd=self.default_cwd)

    def build_env(self, context: object) -> dict[str, str]:
        return self.action_env_builder(
            self.command_name,
            self.targets,
            route=self.route,
            target=getattr(context, "target_obj"),
            extra=self.command_extra_env,
        )

    def process_run(self, command: list[str], cwd: Path, env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
        process_runtime = self.process_runtime
        if process_runtime is None:
            raise RuntimeError("process runtime has not been initialized")
        if self.stream_review_output:
            completed = process_runtime.run_streaming(
                command,
                cwd=cwd,
                env=dict(env),
                timeout=300.0,
                show_spinner=False,
                echo_output=True,
            )
            return subprocess.CompletedProcess(
                args=command,
                returncode=completed.returncode,
                stdout="" if completed.returncode == 0 else str(completed.stdout or ""),
                stderr=str(getattr(completed, "stderr", "") or ""),
            )
        return process_runtime.run(
            command,
            cwd=cwd,
            env=dict(env),
            timeout=300.0,
        )

    def success_print_message(self, context: object, completed: Any) -> str:
        return ship_action_status_message(str(getattr(context, "name")), completed)

    def success_status_message(self, context: object, completed: Any) -> str:
        return ship_action_status_message(str(getattr(context, "name")), completed)

    def _should_stream_review_output(self) -> bool:
        return bool(
            self.command_name == "review"
            and not self.interactive_command
            and self.stdout_is_live_terminal()
            and self.process_runtime is not None
            and hasattr(self.process_runtime, "run_streaming")
        )

    def _command_extra_env(self) -> dict[str, str]:
        command_extra_env = dict(self.extra_env)
        if self.stream_review_output:
            command_extra_env["ENVCTL_ACTION_FORCE_RICH"] = "1"
        return command_extra_env


def run_project_action(
    *,
    runtime: Any,
    route: Route,
    targets: list[object],
    command_name: str,
    env_key: str,
    default_command: list[str] | None,
    default_cwd: Path,
    default_append_project_path: bool,
    extra_env: Mapping[str, str],
    action_replacements_builder: Callable[..., dict[str, str]],
    action_env_builder: Callable[..., dict[str, str]],
    emit_status: Callable[[str], None],
    success_handler: Callable[..., object] | None,
    failure_handler: Callable[..., object] | None,
    stdout_is_live_terminal: Callable[[], bool],
    execute_targeted_action_fn: Callable[..., int],
) -> int:
    return ProjectActionRunner(
        runtime=runtime,
        route=route,
        targets=targets,
        command_name=command_name,
        env_key=env_key,
        default_command=default_command,
        default_cwd=default_cwd,
        default_append_project_path=default_append_project_path,
        extra_env=extra_env,
        action_replacements_builder=action_replacements_builder,
        action_env_builder=action_env_builder,
        emit_status=emit_status,
        success_handler=success_handler,
        failure_handler=failure_handler,
        stdout_is_live_terminal=stdout_is_live_terminal,
        execute_targeted_action_fn=execute_targeted_action_fn,
    ).run()
