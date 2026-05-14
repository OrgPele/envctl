from __future__ import annotations

from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, PlanAgentLaunchConfig
from envctl_engine.runtime.codex_tmux_support import (
    _completed_process_error_text as _tmux_completed_process_error_text,
    _run_probe as _run_tmux_probe,
    _tmux_session_exists,
)


def _ensure_tmux_window(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> str | None:
    from envctl_engine.planning.plan_agent import launch as _launch

    cwd = Path(worktree.root).resolve()
    shell_command = launch_config.shell
    if _tmux_session_exists(runtime, session_name):
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
    result = _run_tmux_probe(runtime, command, cwd=Path(runtime.config.base_dir).resolve())
    if result.returncode == 0:
        option_error = _launch._enable_tmux_mouse_scrollback(runtime, session_name=session_name)
        if option_error is not None:
            return option_error
        wait_error = _launch._wait_for_tmux_window_ready(runtime, session_name=session_name, window_name=window_name)
        if wait_error is None:
            return None
        return wait_error
    return _tmux_completed_process_error_text(result)
