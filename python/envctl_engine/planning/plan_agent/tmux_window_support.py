from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any, Callable

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, PlanAgentLaunchConfig

def enable_tmux_mouse_scrollback(
    runtime: Any,
    *,
    session_name: str,
    run_tmux_probe_fn: Callable[..., subprocess.CompletedProcess[str]],
    completed_process_error_text_fn: Callable[[subprocess.CompletedProcess[str]], str],
) -> str | None:
    result = run_tmux_probe_fn(
        runtime,
        ("tmux", "set-option", "-t", session_name, "mouse", "on"),
        cwd=Path(runtime.config.base_dir).resolve(),
    )
    if result.returncode == 0:
        return None
    return completed_process_error_text_fn(result)


def wait_for_tmux_window_ready(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    tmux_window_exists_fn: Callable[..., bool],
    monotonic_fn: Callable[[], float],
    sleep_fn: Callable[[float], None],
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> str | None:
    deadline = monotonic_fn() + timeout_seconds
    while monotonic_fn() < deadline:
        if tmux_window_exists_fn(runtime, session_name=session_name, window_name=window_name):
            return None
        sleep_fn(poll_interval_seconds)
    return f"tmux_window_unavailable: can't find window: {window_name}"


def tmux_window_exists(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    run_tmux_probe_fn: Callable[..., subprocess.CompletedProcess[str]],
) -> bool:
    result = run_tmux_probe_fn(
        runtime,
        ("tmux", "list-windows", "-t", session_name, "-F", "#{window_name}"),
        cwd=Path(runtime.config.base_dir).resolve(),
    )
    if result.returncode != 0:
        return False
    windows = {str(line).strip() for line in str(getattr(result, "stdout", "")).splitlines() if str(line).strip()}
    return window_name in windows


def ensure_tmux_window(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
    tmux_session_exists_fn: Callable[..., bool],
    run_tmux_probe_fn: Callable[..., subprocess.CompletedProcess[str]],
    completed_process_error_text_fn: Callable[[subprocess.CompletedProcess[str]], str],
    enable_mouse_scrollback_fn: Callable[..., str | None],
    wait_for_window_ready_fn: Callable[..., str | None],
) -> str | None:
    cwd = Path(worktree.root).resolve()
    shell_command = launch_config.shell
    if tmux_session_exists_fn(runtime, session_name):
        command = (
            "tmux",
            "new-window",
            "-d",
            "-t",
            session_name,
            "-n",
            window_name,
            "-c",
            str(cwd),
            shell_command,
        )
    else:
        command = (
            "tmux",
            "new-session",
            "-d",
            "-s",
            session_name,
            "-n",
            window_name,
            "-c",
            str(cwd),
            shell_command,
        )
    result = run_tmux_probe_fn(runtime, command, cwd=Path(runtime.config.base_dir).resolve())
    if result.returncode != 0:
        return completed_process_error_text_fn(result)

    option_error = enable_mouse_scrollback_fn(runtime, session_name=session_name)
    if option_error is not None:
        return option_error
    wait_error = wait_for_window_ready_fn(runtime, session_name=session_name, window_name=window_name)
    if wait_error is None:
        return None
    return wait_error
