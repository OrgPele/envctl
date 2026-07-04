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
    _normalized_screen_text,
    _prompt_picker_screen_looks_ready,
    _prompt_submit_screen_looks_ready,
    _screen_excerpt,
    _screen_looks_ready,
)
from envctl_engine.planning.plan_agent.cmux_workspace_support import surface_id_from_output
from envctl_engine.runtime.runtime_context import resolve_process_runtime


def create_surface(runtime: Any, *, workspace_id: str) -> tuple[str | None, str | None]:
    result = resolve_process_runtime(runtime).run(
        ["cmux", "new-surface", "--workspace", workspace_id],
        cwd=runtime.config.base_dir,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(result, "returncode", 1) != 0:
        return None, completed_process_error_text(result)
    return surface_id_from_output(str(getattr(result, "stdout", ""))), None


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
    key_name = str(key).strip().lower()
    return run_cmux_command(
        runtime,
        ["cmux", "send-key", "--workspace", workspace_id, "--surface", surface_id, key_name],
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
    result = resolve_process_runtime(runtime).run(
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
) -> str | None:
    normalized_cli = str(cli).strip().lower()
    timeout_seconds = cli_ready_delay_seconds
    if normalized_cli not in {"codex", "opencode"}:
        time.sleep(timeout_seconds)
        return None
    deadline = time.monotonic() + timeout_seconds
    last_screen = ""
    while time.monotonic() < deadline:
        last_screen = read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _screen_looks_ready(normalized_cli, last_screen):
            return None
        time.sleep(_CLI_READY_POLL_INTERVAL_SECONDS)
    return _ready_timeout_error(f"{normalized_cli}_ready_timeout", last_screen)


def read_surface_screen(runtime: Any, *, workspace_id: str, surface_id: str) -> str:
    result = resolve_process_runtime(runtime).run(
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
) -> str | None:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli != "opencode":
        if normalized_cli != "codex":
            time.sleep(_PROMPT_SUBMIT_READY_DELAY_SECONDS)
            return None
    deadline = time.monotonic() + _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS
    last_screen = ""
    while time.monotonic() < deadline:
        last_screen = read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _prompt_submit_screen_looks_ready(normalized_cli, last_screen, prompt_text):
            return None
        time.sleep(_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS)
    return _ready_timeout_error(f"{normalized_cli}_prompt_submit_ready_timeout", last_screen)


def wait_for_direct_prompt_ready(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    prompt_text: str,
) -> str | None:
    deadline = time.monotonic() + _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS
    last_screen = ""
    while time.monotonic() < deadline:
        last_screen = read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _direct_prompt_text_is_visible(last_screen, prompt_text):
            return None
        time.sleep(_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS)
    return _ready_timeout_error("direct_prompt_ready_timeout", last_screen)


def _direct_prompt_text_is_visible(screen: str, prompt_text: str) -> bool:
    normalized_screen = _normalized_screen_text(screen)
    normalized_prompt = _normalized_screen_text(prompt_text)
    if not normalized_screen or not normalized_prompt:
        return False
    if len(normalized_prompt) >= 500 and "pasted content" in normalized_screen:
        return True
    return normalized_prompt[:80] in normalized_screen


def wait_for_prompt_picker_ready(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cli: str,
    prompt_text: str,
) -> str | None:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli not in {"codex", "opencode"}:
        time.sleep(_PROMPT_PRE_SUBMIT_DELAY_SECONDS)
        return None
    deadline = time.monotonic() + _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS
    last_screen = ""
    while time.monotonic() < deadline:
        last_screen = read_surface_screen(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _prompt_picker_screen_looks_ready(normalized_cli, last_screen, prompt_text):
            return None
        time.sleep(_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS)
    return _ready_timeout_error(f"{normalized_cli}_prompt_picker_ready_timeout", last_screen)


def _ready_timeout_error(reason: str, screen: str) -> str:
    excerpt = _screen_excerpt(screen)
    if not excerpt:
        return reason
    return f"{reason}: {excerpt}"


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
