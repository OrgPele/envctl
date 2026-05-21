from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from envctl_engine.planning.worktree_project_catalog import (
    cleanup_empty_feature_root,
    feature_project_candidates,
    project_sort_key_for_feature,
)


class WorktreeProjectCatalogTests(unittest.TestCase):
    def test_project_sort_key_orders_base_numeric_iter_and_named_suffixes(self) -> None:
        names = [
            "feature-a-extra",
            "unrelated",
            "feature-a-10",
            "feature-a",
            "feature-a-iter_2",
            "feature-a-1",
            "feature-a-iter3",
        ]

        self.assertEqual(
            sorted(names, key=lambda name: project_sort_key_for_feature(name, "feature-a")),
            [
                "feature-a",
                "feature-a-1",
                "feature-a-iter_2",
                "feature-a-iter3",
                "feature-a-10",
                "feature-a-extra",
                "unrelated",
            ],
        )

    def test_feature_project_candidates_filters_case_insensitively_and_sorts(self) -> None:
        projects = [
            ("feature-a-10", Path("/tmp/feature-a-10")),
            ("feature-a-extra", Path("/tmp/feature-a-extra")),
            ("other", Path("/tmp/other")),
            ("FEATURE-A", Path("/tmp/feature-a")),
            ("feature-a-2", Path("/tmp/feature-a-2")),
            ("feature-ab-1", Path("/tmp/feature-ab-1")),
        ]

        self.assertEqual(
            [name for name, _root in feature_project_candidates(projects=projects, feature="feature-a")],
            ["FEATURE-A", "feature-a-2", "feature-a-10", "feature-a-extra"],
        )

    def test_cleanup_empty_feature_root_removes_only_empty_existing_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            trees_root = Path(tmpdir) / "trees"
            feature_root = trees_root / "feature-a"
            feature_root.mkdir(parents=True)

            cleanup_empty_feature_root(preferred_tree_root_for_feature=lambda _feature: feature_root, feature="feature-a")

            self.assertFalse(feature_root.exists())

    def test_cleanup_empty_feature_root_keeps_missing_and_non_empty_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            trees_root = Path(tmpdir) / "trees"
            missing_root = trees_root / "missing"
            non_empty_root = trees_root / "feature-a"
            (non_empty_root / "1").mkdir(parents=True)

            cleanup_empty_feature_root(preferred_tree_root_for_feature=lambda _feature: missing_root, feature="missing")
            cleanup_empty_feature_root(preferred_tree_root_for_feature=lambda _feature: non_empty_root, feature="feature-a")

            self.assertFalse(missing_root.exists())
            self.assertTrue(non_empty_root.is_dir())

    def test_cleanup_empty_feature_root_ignores_rmdir_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_root = Path(tmpdir) / "trees" / "feature-a"
            feature_root.mkdir(parents=True)

            with patch.object(Path, "rmdir", side_effect=OSError("busy")):
                cleanup_empty_feature_root(
                    preferred_tree_root_for_feature=lambda _feature: feature_root,
                    feature="feature-a",
                )

            self.assertTrue(feature_root.is_dir())


if __name__ == "__main__":
    unittest.main()
