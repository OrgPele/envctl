from __future__ import annotations

import threading

from envctl_engine.runtime.command_router import MODE_TREE_TOKENS, Route
from envctl_engine.state.models import RequirementsResult, ServiceRecord
from envctl_engine.startup.lifecycle import execute_startup_lifecycle
from envctl_engine.startup.protocols import ProjectContextLike, StartupRuntime
from envctl_engine.startup.session import ProjectStartupResult
from envctl_engine.startup.startup_progress import (
    ProjectSpinnerGroup,
    report_progress,
    suppress_timing_output,
)
from envctl_engine.startup.startup_execution_support import (
    start_project_context as start_project_context_impl,
    start_project_services as start_project_services_impl,
    start_requirements_for_project as start_requirements_for_project_impl,
)
from envctl_engine.startup.disabled_startup_resolution import resolve_disabled_startup_mode_with_runtime
from envctl_engine.startup.execution_preparation import prepare_startup_execution_with_runtime
from envctl_engine.startup.post_start_reconcile import reconcile_strict_truth_after_start
from envctl_engine.startup.selected_context_startup import start_selected_contexts_with_runtime
from envctl_engine.startup.context_selection import select_startup_contexts
from envctl_engine.startup.execution_preparation import prepare_startup_execution_with_runtime
from envctl_engine.startup.run_reuse_resolution import resolve_startup_run_reuse_with_runtime
from envctl_engine.startup.startup_selection_support import restart_target_projects
from envctl_engine.startup.session_lifecycle import create_startup_session

_MODE_TREE_TOKENS_NORMALIZED = {str(token).strip().lower() for token in MODE_TREE_TOKENS}
_ProjectSpinnerGroup = ProjectSpinnerGroup


class StartupOrchestrator:
    def __init__(self, runtime: StartupRuntime) -> None:
        self.runtime: StartupRuntime = runtime
        self._progress_lock: threading.Lock = threading.Lock()
        self._last_progress_message_by_project: dict[str | None, str] = {}
        self._shared_dependency_lock: threading.Lock = threading.Lock()
        self._shared_dependency_requirements: RequirementsResult | None = None
        self._shared_dependency_progress_reported: bool = False

    def execute(self, route: Route) -> int:
        return execute_startup_lifecycle(self, route)

    @property
    def project_spinner_group_factory(self) -> type[ProjectSpinnerGroup]:
        return _ProjectSpinnerGroup

    @staticmethod
    def _suppress_timing_output(route: Route | None) -> bool:
        return suppress_timing_output(route)

    def start_project_context(
        self,
        *,
        context: ProjectContextLike,
        mode: str,
        route: Route,
        run_id: str,
    ) -> ProjectStartupResult:
        return start_project_context_impl(
            self,
            context=context,
            mode=mode,
            route=route,
            run_id=run_id,
            report_progress_fn=lambda route, message, *, project=None: report_progress(
                self.runtime,
                route,
                progress_lock=self._progress_lock,
                last_progress_message_by_project=self._last_progress_message_by_project,
                message=message,
                project=project,
            ),
        )

    def start_requirements_for_project(
        self,
        context: ProjectContextLike,
        *,
        mode: str,
        route: Route | None = None,
    ) -> RequirementsResult:
        return start_requirements_for_project_impl(
            self,
            context,
            mode=mode,
            route=route,
            report_progress_fn=lambda route, message, *, project=None: report_progress(
                self.runtime,
                route,
                progress_lock=self._progress_lock,
                last_progress_message_by_project=self._last_progress_message_by_project,
                message=message,
                project=project,
            ),
            suppress_timing_output_fn=suppress_timing_output,
        )

    def start_project_services(
        self,
        context: ProjectContextLike,
        *,
        requirements: RequirementsResult,
        run_id: str,
        route: Route | None = None,
    ) -> dict[str, ServiceRecord]:
        return start_project_services_impl(self, context, requirements=requirements, run_id=run_id, route=route)
