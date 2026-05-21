from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.planning.worktree_sync_deletion import delete_feature_worktrees


class WorktreeSyncDeletionTests(unittest.TestCase):
    def test_delete_feature_worktrees_deletes_highest_iterations_first_and_stops_at_remove_count(self) -> None:
        deleted: list[Path] = []

        error = delete_feature_worktrees(
            feature="backend",
            candidates=[
                ("backend-1", Path("/repo/trees/backend/1")),
                ("backend-3", Path("/repo/trees/backend/3")),
                ("backend-2", Path("/repo/trees/backend/2")),
            ],
            remove_count=2,
            project_sort_key_for_feature=lambda name, _feature: (0, int(name.rsplit("-", 1)[1])),
            active_protection_reason=lambda **_kwargs: "",
            blast_worktree_before_delete=None,
            delete_worktree=lambda *, worktree_root, **_kwargs: deleted.append(worktree_root)
            or SimpleNamespace(success=True, message="deleted"),
            repo_root=Path("/repo"),
            trees_root_for_worktree=lambda root: root.parents[1],
            process_runner=object(),
            emit=lambda *_args, **_kwargs: None,
        )

        self.assertIsNone(error)
        self.assertEqual(deleted, [Path("/repo/trees/backend/3"), Path("/repo/trees/backend/2")])

    def test_delete_feature_worktrees_skips_active_ai_sessions_and_emits_cleanup_warnings(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        warnings = ["failed to stop worker"]
        deleted: list[Path] = []

        error = delete_feature_worktrees(
            feature="backend",
            candidates=[
                ("backend-2", Path("/repo/trees/backend/2")),
                ("backend-1", Path("/repo/trees/backend/1")),
            ],
            remove_count=2,
            project_sort_key_for_feature=lambda name, _feature: (0, int(name.rsplit("-", 1)[1])),
            active_protection_reason=lambda *, name, **_kwargs: "active session" if name == "backend-2" else "",
            blast_worktree_before_delete=lambda **_kwargs: warnings,
            delete_worktree=lambda *, worktree_root, **_kwargs: deleted.append(worktree_root)
            or SimpleNamespace(success=True, message="deleted"),
            repo_root=Path("/repo"),
            trees_root_for_worktree=lambda root: root.parents[1],
            process_runner=object(),
            emit=lambda event, **payload: events.append((event, payload)),
        )

        self.assertIsNone(error)
        self.assertEqual(deleted, [Path("/repo/trees/backend/1")])
        self.assertEqual(events[0][0], "planning.worktree.cleanup.skipped_active_ai_session")
        self.assertEqual(events[0][1]["worktree"], "backend-2")
        self.assertEqual(events[1], ("cleanup.worktree.warning", {"project": "backend-1", "warning": warnings[0], "source_command": "blast-worktree"}))

    def test_delete_feature_worktrees_returns_delete_failure_message(self) -> None:
        error = delete_feature_worktrees(
            feature="backend",
            candidates=[("backend-1", Path("/repo/trees/backend/1"))],
            remove_count=1,
            project_sort_key_for_feature=lambda _name, _feature: (0, 1),
            active_protection_reason=lambda **_kwargs: "",
            blast_worktree_before_delete=None,
            delete_worktree=lambda **_kwargs: SimpleNamespace(success=False, message="delete failed"),
            repo_root=Path("/repo"),
            trees_root_for_worktree=lambda root: root.parents[1],
            process_runner=object(),
            emit=lambda *_args, **_kwargs: None,
        )

        self.assertEqual(error, "delete failed")


if __name__ == "__main__":
    unittest.main()
