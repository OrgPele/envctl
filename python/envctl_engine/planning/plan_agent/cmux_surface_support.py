from __future__ import annotations

import time
from typing import Any

from envctl_engine.planning.plan_agent.constants import (
    _CLI_READY_POLL_INTERVAL_SECONDS,
    _PROMPT_PRE_SUBMIT_DELAY_SECONDS,
    _PROMPT_SUBMIT_READY_DELAY_SECONDS,
    _PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS,
    _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS,
    _READ_SCREEN_LINE_COUNT,
    _SURFACE_READY_DELAY_SECONDS,
)
from envctl_engine.planning.plan_agent.terminal_screen import (
    _prompt_picker_screen_looks_ready,
    _prompt_submit_screen_looks_ready,
    _screen_looks_ready,
)


def send_surface_text(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    text: str,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    return run_cmux_command(
        runtime,
        ["cmux", "send", "--workspace", workspace_id, "--surface", surface_id, text],
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
    )


def paste_surface_text(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    text: str,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    buffer_name = f"envctl-{str(surface_id).replace(':', '-')}"
    set_error = run_cmux_command(
        runtime,
        ["cmux", "set-buffer", "--name", buffer_name, text],
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
    )
    if set_error is not None:
        return set_error
    return run_cmux_command(
        runtime,
        ["cmux", "paste-buffer", "--name", buffer_name, "--workspace", workspace_id, "--surface", surface_id],
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
    )


def send_prompt_text(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cli: str,
    text: str,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    _ = cli
    if failure_event == "planning.agent_launch.failed":
        return send_surface_text(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            text=text,
        )
    return send_surface_text(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        text=text,
        failure_event=failure_event,
    )


def send_surface_key(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    key: str,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    return run_cmux_command(
        runtime,
        ["cmux", "send-key", "--workspace", workspace_id, "--surface", surface_id, key],
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
    )


def run_cmux_command(
    runtime: Any,
    command: list[str],
    *,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    result = runtime.process_runner.run(
        command,
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(result, "returncode", 1) == 0:
        return None
    error = completed_process_error_text(result)
    if emit_failure_event:
        runtime._emit(failure_event, reason="cmux_command_failed", command=command[1], error=error)
    return error


def completed_process_error_text(result: object) -> str:
    stderr = str(getattr(result, "stderr", "")).strip()
    stdout = str(getattr(result, "stdout", "")).strip()
    if stderr:
        return stderr
    if stdout:
        return stdout
    return f"exit:{getattr(result, 'returncode', 1)}"


def wait_for_cli_ready(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cli: str,
    cli_ready_delay_seconds: float,
) -> None:
    normalized_cli = str(cli).strip().lower()
    timeout_seconds = cli_ready_delay_seconds
    if normalized_cli not in {"codex", "opencode"}:
        time.sleep(timeout_seconds)
        return
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        screen = read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _screen_looks_ready(normalized_cli, screen):
            return
        time.sleep(_CLI_READY_POLL_INTERVAL_SECONDS)


def read_surface_screen(runtime: Any, *, workspace_id: str, surface_id: str) -> str:
    result = runtime.process_runner.run(
        [
            "cmux",
            "read-screen",
            "--workspace",
            workspace_id,
            "--surface",
            surface_id,
            "--lines",
            str(_READ_SCREEN_LINE_COUNT),
        ],
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(result, "returncode", 1) != 0:
        return ""
    return str(getattr(result, "stdout", ""))


def wait_for_prompt_submit_ready(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cli: str,
    prompt_text: str,
) -> None:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli != "opencode":
        if normalized_cli != "codex":
            time.sleep(_PROMPT_SUBMIT_READY_DELAY_SECONDS)
            return
    deadline = time.monotonic() + _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        screen = read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _prompt_submit_screen_looks_ready(normalized_cli, screen, prompt_text):
            return
        time.sleep(_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS)


def wait_for_prompt_picker_ready(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cli: str,
    prompt_text: str,
) -> None:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli not in {"codex", "opencode"}:
        time.sleep(_PROMPT_PRE_SUBMIT_DELAY_SECONDS)
        return
    deadline = time.monotonic() + _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        screen = read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _prompt_picker_screen_looks_ready(normalized_cli, screen, prompt_text):
            return
        time.sleep(_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS)


def prepare_surface(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    tab_title: str,
    shell_command: str,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    commands = [
        ["cmux", "rename-tab", "--workspace", workspace_id, "--surface", surface_id, tab_title],
        ["cmux", "respawn-pane", "--workspace", workspace_id, "--surface", surface_id, "--command", shell_command],
    ]
    for command in commands:
        error = run_cmux_command(runtime, command, failure_event=failure_event)
        if error is not None:
            return error
    time.sleep(_SURFACE_READY_DELAY_SECONDS)
    return None
