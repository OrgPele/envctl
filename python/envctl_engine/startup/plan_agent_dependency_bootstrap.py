from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import time
from typing import Any, ClassVar

from envctl_engine.startup.dependency_bootstrap import prepare_project_dependencies
from envctl_engine.startup.session import StartupSession


@dataclass(frozen=True, slots=True)
class PlanAgentDependencyBootstrapper:
    __test__: ClassVar[bool] = False

    runtime: Any
    session: StartupSession
    created_worktrees: tuple[Any, ...]
    launch_config: object
    report_progress: Callable[..., None]
    prepare_fn: Callable[..., Any] = prepare_project_dependencies
    monotonic_fn: Callable[[], float] = time.monotonic

    def prepare(self) -> None:
        if not bool(getattr(self.launch_config, "enabled", False)) or not self.created_worktrees:
            return
        route = self.session.effective_route
        if route.flags.get("launch_dependencies") is False:
            self.runtime._emit(
                "planning.dependency_bootstrap.finish",
                status="skipped",
                reason="disabled_by_flag",
                project_count=0,
                duration_ms=0.0,
            )
            return

        bootstrap_started = self.monotonic_fn()
        self._emit_start()
        try:
            results = self._prepare_projects()
        except Exception as exc:
            self.runtime._emit(
                "planning.dependency_bootstrap.finish",
                status="failed",
                error=str(exc),
                duration_ms=round((self.monotonic_fn() - bootstrap_started) * 1000.0, 2),
            )
            raise

        self.session.plan_agent_dependency_bootstrap_results = tuple(results)
        self.runtime._emit(
            "planning.dependency_bootstrap.finish",
            status="ok",
            project_count=len(results),
            duration_ms=round((self.monotonic_fn() - bootstrap_started) * 1000.0, 2),
        )

    def _emit_start(self) -> None:
        self.runtime._emit(
            "planning.dependency_bootstrap.start",
            project_count=len(self.created_worktrees),
            projects=[worktree.name for worktree in self.created_worktrees],
            cli=getattr(self.launch_config, "cli", ""),
            transport=getattr(self.launch_config, "transport", ""),
        )

    def _prepare_projects(self) -> list[Any]:
        route = self.session.effective_route
        context_by_name = {context.name: context for context in self.session.selected_contexts}
        results: list[Any] = []
        for worktree in self.created_worktrees:
            context = context_by_name.get(worktree.name)
            if context is None:
                continue
            self.report_progress(
                route,
                f"Preparing dependencies for {worktree.name}...",
                project=worktree.name,
            )
            project_started = self.monotonic_fn()
            result = self.prepare_fn(
                self.runtime,
                context=context,
                route=route,
                run_id=self.session.run_id,
            )
            results.append(result)
            self._emit_project_ready(worktree=worktree, result=result, project_started=project_started)
            self.report_progress(
                route,
                (
                    f"Dependencies ready for {worktree.name}: "
                    f"backend={result.backend.manager} frontend={result.frontend.manager}"
                ),
                project=worktree.name,
            )
        return results

    def _emit_project_ready(self, *, worktree: Any, result: Any, project_started: float) -> None:
        self.runtime._emit(
            "planning.dependency_bootstrap.project",
            project=worktree.name,
            status="ok",
            backend_manager=result.backend.manager,
            frontend_manager=result.frontend.manager,
            skipped=list(result.skipped),
            duration_ms=round((self.monotonic_fn() - project_started) * 1000.0, 2),
        )


def prepare_plan_agent_dependencies_for_launch(
    runtime: Any,
    session: StartupSession,
    *,
    created_worktrees: tuple[Any, ...],
    launch_config: object,
    report_progress: Callable[..., None],
    prepare_fn: Callable[..., Any] = prepare_project_dependencies,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> None:
    PlanAgentDependencyBootstrapper(
        runtime=runtime,
        session=session,
        created_worktrees=created_worktrees,
        launch_config=launch_config,
        report_progress=report_progress,
        prepare_fn=prepare_fn,
        monotonic_fn=monotonic_fn,
    ).prepare()
