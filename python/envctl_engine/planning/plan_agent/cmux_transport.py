from __future__ import annotations

import time
from typing import Any


def _prepare_surface(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    tab_title: str,
    shell_command: str,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    from envctl_engine.planning.plan_agent import launch as _launch

    commands = [
        ["cmux", "rename-tab", "--workspace", workspace_id, "--surface", surface_id, tab_title],
        ["cmux", "respawn-pane", "--workspace", workspace_id, "--surface", surface_id, "--command", shell_command],
    ]
    for command in commands:
        error = _launch._run_cmux_command(runtime, command, failure_event=failure_event)
        if error is not None:
            return error
    time.sleep(_launch._SURFACE_READY_DELAY_SECONDS)
    return None
