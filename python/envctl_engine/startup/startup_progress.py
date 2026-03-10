from __future__ import annotations

import threading
from typing import Any

from envctl_engine.startup.progress_shared import BaseProjectSpinnerGroup


class ProjectSpinnerGroup(BaseProjectSpinnerGroup):
    def __init__(
        self,
        *,
        projects: list[str],
        enabled: bool,
        policy: Any,
        emit: Any,
        component: str,
        op_id: str,
        env: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            projects=projects,
            enabled=enabled,
            policy=policy,
            emit=emit,
            component=component,
            op_id=op_id,
            start_message=(
                f"Starting {len([str(project).strip() for project in projects if str(project).strip()])} project(s)..."
            ),
            idle_message="running...",
            env=env,
        )


def suppress_progress_output(route: Any) -> bool:
    if bool(route.flags.get("debug_suppress_progress_output")):
        return True
    return bool(route.flags.get("interactive_command"))


def suppress_timing_output(route: Any | None) -> bool:
    if route is None:
        return False
    if bool(route.flags.get("_suppress_timing_print")):
        return True
    if callable(route.flags.get("_spinner_update")):
        return True
    if callable(route.flags.get("_spinner_update_project")):
        return True
    return False


def report_progress(
    runtime: Any,
    route: Any,
    *,
    progress_lock: threading.Lock,
    last_progress_message_by_project: dict[str | None, str],
    message: str,
    project: str | None = None,
) -> None:
    normalized_message = str(message).strip()
    with progress_lock:
        previous = last_progress_message_by_project.get(project)
        if previous == normalized_message:
            return
        last_progress_message_by_project[project] = normalized_message
    project_spinner_update = route.flags.get("_spinner_update_project")
    if project and callable(project_spinner_update):
        project_spinner_update(project, message)
        runtime._emit(  # type: ignore[attr-defined]
            "ui.spinner.lifecycle",
            component="startup_orchestrator",
            op_id="startup.execute",
            state="update",
            project=project,
            message=message,
        )
        return
    spinner_update = route.flags.get("_spinner_update")
    if callable(spinner_update):
        spinner_update(message)
        runtime._emit(  # type: ignore[attr-defined]
            "ui.spinner.lifecycle",
            component="startup_orchestrator",
            op_id="startup.execute",
            state="update",
            message=message,
        )
        return
    if suppress_progress_output(route):
        runtime._emit("ui.status", message=message)  # type: ignore[attr-defined]
        return
    print(message)
