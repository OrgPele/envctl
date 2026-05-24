from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from envctl_engine.planning.plan_agent.models import PlanWorktreeSyncResult
from envctl_engine.planning.worktree_plan_project_selection import select_plan_projects
from envctl_engine.runtime.command_router import Route


class ProjectContext:
    def __init__(self, name: str, root: Path) -> None:
        self.name = name
        self.root = root


class WorktreePlanProjectSelectionTests(unittest.TestCase):
    def test_passthrough_filters_existing_projects_when_no_planning_files_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            contexts = [
                ProjectContext("Main", root),
                ProjectContext("api-1", root / "trees" / "api" / "1"),
                ProjectContext("web-1", root / "trees" / "web" / "1"),
            ]

            result = select_plan_projects(
                route=Route(command="start", mode="plan", passthrough_args=["api"]),
                project_contexts=contexts,
                config=self._config(root),
                env={},
                emit=self._unexpected_emit,
                contexts_from_raw_projects=self._contexts_from_raw_projects,
                duplicate_project_context_error=lambda _contexts: None,
                planning_keep_plan_enabled=lambda _route: False,
                prompt_planning_selection=self._unexpected,
                sync_plan_worktrees_from_plan_counts=self._unexpected,
            )

        self.assertIsNone(result.error)
        self.assertEqual([context.name for context in result.selected_contexts], ["api-1"])

    def test_invalid_planning_selector_records_error_and_emits_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            planning_dir = root / "todo" / "plans"
            (planning_dir / "features").mkdir(parents=True)
            (planning_dir / "features" / "known.md").write_text("# known\n", encoding="utf-8")
            events: list[tuple[str, dict[str, object]]] = []

            result = select_plan_projects(
                route=Route(command="start", mode="plan", passthrough_args=["missing"]),
                project_contexts=[],
                config=self._config(root),
                env={},
                emit=lambda event, **payload: events.append((event, payload)),
                contexts_from_raw_projects=self._contexts_from_raw_projects,
                duplicate_project_context_error=lambda _contexts: None,
                planning_keep_plan_enabled=lambda _route: False,
                prompt_planning_selection=self._unexpected,
                sync_plan_worktrees_from_plan_counts=self._unexpected,
            )

        self.assertEqual(result.error, "Planning file not found: missing")
        self.assertEqual(result.selected_contexts, [])
        self.assertEqual(events[0][0], "planning.selection.invalid")
        self.assertEqual(events[0][1]["selection"], "missing")

    def test_dry_run_predicts_created_worktree_contexts_without_syncing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            planning_dir = root / "todo" / "plans"
            (planning_dir / "implementations").mkdir(parents=True)
            (planning_dir / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            result = select_plan_projects(
                route=Route(
                    command="start",
                    mode="plan",
                    passthrough_args=["task"],
                    flags={"dry_run": True},
                ),
                project_contexts=[],
                config=self._config(root),
                env={},
                emit=self._unexpected_emit,
                contexts_from_raw_projects=self._contexts_from_raw_projects,
                duplicate_project_context_error=lambda _contexts: None,
                planning_keep_plan_enabled=lambda _route: False,
                prompt_planning_selection=self._unexpected,
                sync_plan_worktrees_from_plan_counts=self._unexpected,
            )

        self.assertIsNone(result.error)
        self.assertEqual([context.name for context in result.selected_contexts], ["implementations_task-1"])
        self.assertEqual([item.name for item in result.created_worktrees], ["implementations_task-1"])
        self.assertEqual(result.created_worktrees[0].plan_file, "implementations/task.md")

    def test_sync_error_returns_created_worktree_context_and_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            planning_dir = root / "todo" / "plans"
            (planning_dir / "implementations").mkdir(parents=True)
            (planning_dir / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            result = select_plan_projects(
                route=Route(command="start", mode="plan", passthrough_args=["task"]),
                project_contexts=[],
                config=self._config(root),
                env={},
                emit=self._unexpected_emit,
                contexts_from_raw_projects=self._contexts_from_raw_projects,
                duplicate_project_context_error=lambda _contexts: None,
                planning_keep_plan_enabled=lambda _route: False,
                prompt_planning_selection=self._unexpected,
                sync_plan_worktrees_from_plan_counts=lambda **kwargs: PlanWorktreeSyncResult(
                    raw_projects=list(kwargs["raw_projects"]),
                    error="sync failed",
                ),
            )

        self.assertEqual(result.error, "sync failed")
        self.assertEqual(result.selected_contexts, [])

    def _config(self, root: Path) -> SimpleNamespace:
        return SimpleNamespace(
            base_dir=root,
            planning_dir=root / "todo" / "plans",
            trees_dir_name="trees",
            plan_strict_selection=False,
            raw={},
        )

    def _contexts_from_raw_projects(self, raw_projects: list[tuple[str, Path]]) -> list[ProjectContext]:
        return [ProjectContext(name, Path(root)) for name, root in raw_projects]

    def _unexpected_emit(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("emit should not be called")

    def _unexpected(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("callback should not be called")
