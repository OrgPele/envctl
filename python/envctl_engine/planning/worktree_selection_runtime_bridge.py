from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import PlanSelectionResult
from envctl_engine.planning.protocols import ProjectContextLike
from envctl_engine.planning.worktree_plan_project_selection import select_plan_projects
from envctl_engine.planning.worktree_prompt_selection import prompt_planning_selection
from envctl_engine.runtime.command_router import Route


@dataclass(slots=True)
class WorktreeSelectionRuntimeBridge:
    """Wires runtime collaborators into plan selection and planning-menu owners."""

    runtime: Any
    select_planning_counts: Callable[..., Any]

    def select_plan_projects(
        self,
        route: Route,
        project_contexts: list[ProjectContextLike],
    ) -> list[ProjectContextLike]:
        runtime = self.runtime
        setattr(runtime, "_last_plan_selection_result", PlanSelectionResult(raw_projects=[], selected_contexts=[]))
        selection_result = select_plan_projects(
            route=route,
            project_contexts=project_contexts,
            config=runtime.config,
            env=getattr(runtime, "env", {}),
            emit=runtime._emit,
            contexts_from_raw_projects=runtime._contexts_from_raw_projects,
            duplicate_project_context_error=runtime._duplicate_project_context_error,
            planning_keep_plan_enabled=runtime._planning_keep_plan_enabled,
            prompt_planning_selection=runtime._prompt_planning_selection,
            sync_plan_worktrees_from_plan_counts=runtime._sync_plan_worktrees_from_plan_counts,
        )
        setattr(runtime, "_last_plan_selection_result", selection_result)
        return selection_result.selected_contexts

    def prompt_planning_selection(
        self,
        planning_files: list[str],
        raw_projects: list[tuple[str, Path]],
        *,
        persist_memory: bool = True,
    ) -> dict[str, int] | None:
        runtime = self.runtime
        return prompt_planning_selection(
            planning_files=planning_files,
            raw_projects=raw_projects,
            initial_plan_selected_counts=runtime._initial_plan_selected_counts,
            run_planning_selection_menu=runtime._run_planning_selection_menu,
            save_plan_selection_memory=runtime._save_plan_selection_memory,
            persist_memory=persist_memory,
        )

    def run_planning_selection_menu(
        self,
        *,
        planning_files: list[str],
        selected_counts: dict[str, int],
        existing_counts: dict[str, int],
    ) -> dict[str, int] | None:
        from envctl_engine.planning.worktree_planning_menu import run_planning_selection_menu

        runtime = self.runtime
        return run_planning_selection_menu(
            planning_files=planning_files,
            selected_counts=selected_counts,
            existing_counts=existing_counts,
            flush_pending_interactive_input=runtime._flush_pending_interactive_input,
            emit=getattr(runtime, "_emit", None),
            select_planning_counts=self.select_planning_counts,
        )
