from __future__ import annotations

from typing import Any

from envctl_engine.startup.progress_shared import BaseProjectSpinnerGroup


class _ResumeProjectSpinnerGroup(BaseProjectSpinnerGroup):
    def __init__(
        self,
        *,
        projects: list[str],
        enabled: bool,
        policy: Any,
        emit: Any,
        env: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            projects=projects,
            enabled=enabled,
            policy=policy,
            emit=emit,
            component="resume.restore",
            op_id="resume.restore",
            start_message=(
                "Preparing stale restore for "
                f"{len([str(project).strip() for project in projects if str(project).strip()])} "
                "project(s)..."
            ),
            idle_message="restoring...",
            env=env,
        )


ResumeProjectSpinnerGroup = _ResumeProjectSpinnerGroup
