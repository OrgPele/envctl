from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from envctl_engine.planning.worktree_path_support import (
    planning_done_root,
    planning_root,
    preferred_tree_root_for_feature,
    resolve_planning_selection_target,
    setup_worktree_requested,
    trees_root_for_worktree,
)
from envctl_engine.runtime.command_router import Route


class WorktreePathSupportTests(unittest.TestCase):
    def test_preferred_tree_root_supports_nested_empty_and_legacy_flat_layouts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)

            self.assertEqual(
                preferred_tree_root_for_feature(base_dir=base, trees_dir_name="trees", feature="feature-a"),
                base / "trees" / "feature-a",
            )
            self.assertEqual(
                preferred_tree_root_for_feature(base_dir=base, trees_dir_name="", feature="feature-a"),
                base / "trees" / "feature-a",
            )

            flat = base / "trees-feature-a"
            flat.mkdir()
            self.assertEqual(
                preferred_tree_root_for_feature(base_dir=base, trees_dir_name="trees", feature="feature-a"),
                flat,
            )

    def test_trees_root_for_worktree_detects_nested_and_flat_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            nested = base / "trees" / "feature-a" / "1"
            nested.mkdir(parents=True)
            flat = base / "trees-feature-b" / "2"
            flat.mkdir(parents=True)

            self.assertEqual(
                trees_root_for_worktree(base_dir=base, trees_dir_name="trees", worktree_root=nested),
                base / "trees",
            )
            self.assertEqual(
                trees_root_for_worktree(base_dir=base, trees_dir_name="trees", worktree_root=flat),
                (base / "trees-feature-b").resolve(),
            )

    def test_resolve_planning_selection_target_accepts_indexes_paths_and_basenames(self) -> None:
        base_dir = Path("/repo")
        planning_dir = base_dir / "todo" / "plans"
        planning_files = ["feature-a.md", "nested/feature-b.md"]

        self.assertEqual(
            resolve_planning_selection_target(
                target_token="2",
                planning_files=planning_files,
                planning_dir=planning_dir,
                base_dir=base_dir,
            ),
            "nested/feature-b.md",
        )
        self.assertEqual(
            resolve_planning_selection_target(
                target_token="/repo/todo/plans/feature-a",
                planning_files=planning_files,
                planning_dir=planning_dir,
                base_dir=base_dir,
            ),
            "feature-a.md",
        )
        self.assertEqual(
            resolve_planning_selection_target(
                target_token="feature-b",
                planning_files=planning_files,
                planning_dir=planning_dir,
                base_dir=base_dir,
            ),
            "nested/feature-b.md",
        )

    def test_resolve_planning_selection_target_reports_invalid_and_ambiguous_inputs(self) -> None:
        base_dir = Path("/repo")
        planning_dir = base_dir / "todo" / "plans"

        with self.assertRaisesRegex(ValueError, "Missing planning selection target"):
            resolve_planning_selection_target(
                target_token=" ",
                planning_files=["feature-a.md"],
                planning_dir=planning_dir,
                base_dir=base_dir,
            )
        with self.assertRaisesRegex(ValueError, "Invalid plan index"):
            resolve_planning_selection_target(
                target_token="2",
                planning_files=["feature-a.md"],
                planning_dir=planning_dir,
                base_dir=base_dir,
            )
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            resolve_planning_selection_target(
                target_token="feature-a",
                planning_files=["one/feature-a.md", "two/feature-a.md"],
                planning_dir=planning_dir,
                base_dir=base_dir,
            )
        with self.assertRaisesRegex(ValueError, "Planning file not found"):
            resolve_planning_selection_target(
                target_token="missing",
                planning_files=["feature-a.md"],
                planning_dir=planning_dir,
                base_dir=base_dir,
            )

    def test_planning_roots_and_setup_request_flags(self) -> None:
        planning_dir = Path("/repo/todo/plans")
        self.assertEqual(planning_root(planning_dir=planning_dir), planning_dir)
        self.assertEqual(planning_done_root(planning_dir=planning_dir), Path("/repo/todo/done"))
        self.assertTrue(
            setup_worktree_requested(
                Route(command="plan", mode="main", flags={"setup_worktree": ["feature:1"]})
            )
        )
        self.assertFalse(setup_worktree_requested(Route(command="plan", mode="main", flags={})))


if __name__ == "__main__":
    unittest.main()
