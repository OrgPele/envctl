from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping

from envctl_engine.actions.action_target_support import ActionCommandResolution
from envctl_engine.runtime.command_router import Route


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
    raw = runtime.env.get(env_key)
    interactive_command = bool(route.flags.get("interactive_command"))
    command_extra_env = dict(extra_env)
    stream_review_output = bool(
        command_name == "review"
        and not interactive_command
        and stdout_is_live_terminal()
        and hasattr(runtime.process_runner, "run_streaming")
    )
    if stream_review_output:
        command_extra_env["ENVCTL_ACTION_FORCE_RICH"] = "1"
    if raw is None and default_command is None:
        print(f"No {command_name} command configured. Set {env_key} or add repo utility script.")
        return 1

    def resolve_command(context: object) -> ActionCommandResolution:
        target = getattr(context, "target_obj")
        target_root = Path(str(getattr(context, "root")))
        replacements = action_replacements_builder(targets, target=target)
        if raw is not None:
            try:
                command = runtime.split_command(raw, replacements=replacements)
            except RuntimeError as exc:
                return ActionCommandResolution(command=None, cwd=None, error=str(exc))
            return ActionCommandResolution(command=command, cwd=target_root)

        command: list[str] = []
        for token in list(default_command or []):
            value = str(token)
            for key, replacement in replacements.items():
                value = value.replace(f"{{{key}}}", replacement)
            command.append(value)
        if default_append_project_path:
            command.append(str(target_root))
        return ActionCommandResolution(command=command, cwd=default_cwd)

    def build_env(context: object) -> dict[str, str]:
        return action_env_builder(
            command_name,
            targets,
            route=route,
            target=getattr(context, "target_obj"),
            extra=command_extra_env,
        )

    def process_run(command: list[str], cwd: Path, env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
        if stream_review_output:
            completed = runtime.process_runner.run_streaming(
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
        return runtime.process_runner.run(
            command,
            cwd=cwd,
            env=dict(env),
            timeout=300.0,
        )

    return execute_targeted_action_fn(
        targets=targets,
        command_name=command_name,
        interactive_command=interactive_command,
        resolve_command=resolve_command,
        build_env=build_env,
        process_run=process_run,
        emit_status=emit_status,
        interactive_print_failures=(not interactive_command) or command_name in {"pr", "review"},
        emit_success_output=not stream_review_output,
        on_success=success_handler,
        on_failure=failure_handler,
    )
