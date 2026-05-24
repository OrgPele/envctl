from __future__ import annotations

import os
import subprocess
from pathlib import Path
from collections.abc import Callable
from typing import Any

from envctl_engine.runtime.codex_tmux_support import (
    _completed_process_error_text as _tmux_completed_process_error_text,
    _run_probe as _run_tmux_probe,
)


RunTmuxProbeFn = Callable[..., subprocess.CompletedProcess[str]]
CompletedProcessErrorTextFn = Callable[[subprocess.CompletedProcess[str]], str]


def tmux_target(session_name: str, window_name: str) -> str:
    normalized_window = str(window_name).strip()
    if normalized_window.startswith("%"):
        return normalized_window
    if not normalized_window:
        return session_name
    return f"{session_name}:{normalized_window}"


def run_tmux_command(
    runtime: Any,
    command: tuple[str, ...],
    *,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
    run_tmux_probe_fn: Any = _run_tmux_probe,
    completed_process_error_text_fn: CompletedProcessErrorTextFn = _tmux_completed_process_error_text,
) -> str | None:
    result = run_tmux_probe_fn(runtime, command, cwd=Path(runtime.config.base_dir).resolve())
    if result.returncode == 0:
        return None
    error = completed_process_error_text_fn(result)
    if emit_failure_event:
        runtime._emit(failure_event, reason="tmux_command_failed", command=command[1], error=error)
    return error


def send_tmux_text(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    text: str,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
    run_tmux_probe_fn: Any = _run_tmux_probe,
    completed_process_error_text_fn: CompletedProcessErrorTextFn = _tmux_completed_process_error_text,
) -> str | None:
    return run_tmux_command(
        runtime,
        ("tmux", "send-keys", "-t", tmux_target(session_name, window_name), "-l", text),
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
        run_tmux_probe_fn=run_tmux_probe_fn,
        completed_process_error_text_fn=completed_process_error_text_fn,
    )


def send_tmux_key(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    key: str,
    emit_failure_event: bool = True,
    failure_event: str = "planning.agent_launch.failed",
    run_tmux_probe_fn: Any = _run_tmux_probe,
    completed_process_error_text_fn: CompletedProcessErrorTextFn = _tmux_completed_process_error_text,
) -> str | None:
    key_name = {"enter": "Enter"}.get(str(key).strip().lower(), key)
    return run_tmux_command(
        runtime,
        ("tmux", "send-keys", "-t", tmux_target(session_name, window_name), key_name),
        emit_failure_event=emit_failure_event,
        failure_event=failure_event,
        run_tmux_probe_fn=run_tmux_probe_fn,
        completed_process_error_text_fn=completed_process_error_text_fn,
    )


def read_tmux_screen(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    run_tmux_probe_fn: Any = _run_tmux_probe,
) -> str:
    target = tmux_target(session_name, window_name)
    for command in (
        ("tmux", "capture-pane", "-p", "-a", "-t", target),
        ("tmux", "capture-pane", "-p", "-t", target),
    ):
        result = run_tmux_probe_fn(runtime, command, cwd=Path(runtime.config.base_dir).resolve())
        if result.returncode == 0:
            return str(getattr(result, "stdout", ""))
    return ""


def send_tmux_prompt(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    text: str,
    subprocess_module: Any = subprocess,
) -> str | None:
    target = tmux_target(session_name, window_name)
    tmux_env = dict(os.environ)
    tmux_env.update(dict(getattr(runtime, "env", {}) or {}))
    load_result = subprocess_module.run(
        ["tmux", "load-buffer", "-t", target, "-"],
        input=text,
        capture_output=True,
        text=True,
        cwd=Path(runtime.config.base_dir).resolve(),
        env=tmux_env,
        timeout=10.0,
    )
    if load_result.returncode != 0:
        error = (load_result.stderr or "").strip()[:200]
        runtime._emit("planning.agent_launch.failed", reason="tmux_load_buffer_failed", error=error)
        return f"tmux_load_buffer_failed: {error}"
    paste_result = subprocess_module.run(
        ["tmux", "paste-buffer", "-dpr", "-t", target],
        capture_output=True,
        text=True,
        cwd=Path(runtime.config.base_dir).resolve(),
        env=tmux_env,
        timeout=10.0,
    )
    if paste_result.returncode != 0:
        error = (paste_result.stderr or "").strip()[:200]
        runtime._emit("planning.agent_launch.failed", reason="tmux_paste_buffer_failed", error=error)
        return f"tmux_paste_buffer_failed: {error}"
    return None


__all__ = tuple(name for name in globals() if not name.startswith("__"))
