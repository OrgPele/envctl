from __future__ import annotations

import unittest
from collections import OrderedDict
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, PlanWorktreeSyncResult
from envctl_engine.planning.worktree_sync_orchestration import (
    sync_plan_worktrees_from_plan_counts,
    sync_single_plan_worktree_target,
)


class WorktreeSyncOrchestrationTests(unittest.TestCase):
    def test_sync_plan_worktrees_aggregates_results_and_stops_on_error(self) -> None:
        created = CreatedPlanWorktree(name="feature_a-1", root=Path("/repo/trees/feature_a/1"), plan_file="a.md")
        calls: list[tuple[str, list[tuple[str, Path]]]] = []

        def sync_single(**kwargs: Any) -> PlanWorktreeSyncResult:
            calls.append((kwargs["plan_file"], list(kwargs["projects"])))
            if kwargs["plan_file"] == "a.md":
                return PlanWorktreeSyncResult(
                    raw_projects=[("feature_a-1", Path("/repo/trees/feature_a/1"))],
                    created_worktrees=(created,),
                    removed_worktrees=("old-a",),
                    archived_plan_files=("old-a.md",),
                )
            return PlanWorktreeSyncResult(
                raw_projects=list(kwargs["projects"]),
                error="sync failed",
            )

        result = sync_plan_worktrees_from_plan_counts(
            plan_counts=OrderedDict([("a.md", 1), ("b.md", 1)]),
            raw_projects=[],
            keep_plan=True,
            ensure_trees_root=lambda: None,
            env={"ENVCTL_SPINNER": "off"},
            emit=None,
            sync_single_plan_worktree_target=sync_single,
        )

        self.assertEqual(result.error, "sync failed")
        self.assertEqual(result.created_worktrees, (created,))
        self.assertEqual(result.removed_worktrees, ("old-a",))
        self.assertEqual(result.archived_plan_files, ("old-a.md",))
        self.assertEqual(calls[1][1], [("feature_a-1", Path("/repo/trees/feature_a/1"))])

    def test_sync_single_plan_worktree_target_creates_missing_worktrees(self) -> None:
        created = CreatedPlanWorktree(name="implementations_task-1", root=Path("/repo/trees/feature/1"), plan_file="x")
        updates: list[str] = []

        result = sync_single_plan_worktree_target(
            plan_file="implementations/task.md",
            desired_raw=2,
            projects=[("implementations_task-1", Path("/repo/trees/implementations_task/1"))],
            keep_plan=True,
            feature_project_candidates=lambda *, projects, feature: [
                project for project in projects if project[0].startswith(feature)
            ],
            create_feature_worktrees_result=lambda **_kwargs: PlanWorktreeSyncResult(
                raw_projects=[],
                created_worktrees=(created,),
            ),
            discover_tree_projects=lambda: [
                ("implementations_task-1", Path("/repo/trees/implementations_task/1")),
                ("implementations_task-2", Path("/repo/trees/implementations_task/2")),
            ],
            delete_feature_worktrees=self._unexpected,
            cleanup_empty_feature_root=self._unexpected,
            move_plan_to_done=self._unexpected,
            render_planning_path=lambda **kwargs: kwargs["plan_file"],
            update=lambda **kwargs: updates.append(kwargs["message"]),
            output=self._unexpected,
        )

        self.assertIsNone(result.error)
        self.assertEqual(result.created_worktrees, (created,))
        self.assertEqual(len(result.raw_projects), 2)
        self.assertEqual(updates, ["Setting up 1 worktree(s) for implementations/task.md -> implementations_task..."])

    def test_sync_single_plan_worktree_target_deletes_and_archives_zero_count(self) -> None:
        deleted: list[tuple[str, int]] = []
        cleaned: list[str] = []
        archived: list[str] = []
        outputs: list[str] = []

        result = sync_single_plan_worktree_target(
            plan_file="implementations/task.md",
            desired_raw=0,
            projects=[
                ("implementations_task-1", Path("/repo/trees/implementations_task/1")),
                ("implementations_task-2", Path("/repo/trees/implementations_task/2")),
            ],
            keep_plan=False,
            feature_project_candidates=lambda *, projects, feature: [
                project for project in projects if project[0].startswith(feature)
            ],
            create_feature_worktrees_result=self._unexpected,
            discover_tree_projects=lambda: [],
            delete_feature_worktrees=lambda **kwargs: deleted.append((kwargs["feature"], kwargs["remove_count"]))
            or None,
            cleanup_empty_feature_root=lambda *, feature: cleaned.append(feature),
            move_plan_to_done=lambda plan_file: archived.append(plan_file),
            render_planning_path=lambda **kwargs: kwargs["plan_file"],
            update=lambda **_kwargs: None,
            output=outputs.append,
        )

        self.assertIsNone(result.error)
        self.assertEqual(result.raw_projects, [])
        self.assertEqual(result.removed_worktrees, ("implementations_task-1", "implementations_task-2"))
        self.assertEqual(result.archived_plan_files, ("implementations/task.md",))
        self.assertEqual(deleted, [("implementations_task", 2)])
        self.assertEqual(cleaned, ["implementations_task"])
        self.assertEqual(archived, ["implementations/task.md"])
        self.assertEqual(outputs, ["Blasted and deleted 2 worktree(s) for implementations/task.md."])

    def _unexpected(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("callback should not be called")
