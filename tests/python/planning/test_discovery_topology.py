from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.planning import discover_tree_projects


class DiscoveryTopologyTests(unittest.TestCase):
    def test_prefers_nested_feature_iteration_roots_over_app_leaf_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            trees = repo / "trees"
            (trees / "feature-a" / "1" / "backend" / "src").mkdir(parents=True, exist_ok=True)
            (trees / "feature-a" / "1" / "frontend" / "src").mkdir(parents=True, exist_ok=True)
            (trees / "feature-a" / "2" / "backend").mkdir(parents=True, exist_ok=True)
            (trees / "feature-b" / "1" / "node_modules").mkdir(parents=True, exist_ok=True)
            (trees / "flat-tree-x" / "backend").mkdir(parents=True, exist_ok=True)
            (trees / "flat-tree-y" / "frontend").mkdir(parents=True, exist_ok=True)

            projects = discover_tree_projects(repo, "trees")
            names = [name for name, _root in projects]

            self.assertIn("feature-a-1", names)
            self.assertIn("feature-a-2", names)
            self.assertIn("feature-b-1", names)
            self.assertIn("flat-tree-x", names)
            self.assertIn("flat-tree-y", names)
            self.assertNotIn("feature-a-1-backend-src", names)
            self.assertNotIn("feature-a-1-frontend-src", names)

    def test_order_is_stable_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            trees = repo / "trees"
            (trees / "feature-z" / "2").mkdir(parents=True, exist_ok=True)
            (trees / "feature-z" / "1").mkdir(parents=True, exist_ok=True)
            (trees / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            first = discover_tree_projects(repo, "trees")
            second = discover_tree_projects(repo, "trees")

            self.assertEqual(first, second)
            self.assertEqual([name for name, _ in first], ["feature-a-1", "feature-z-1", "feature-z-2"])

    def test_discovers_flat_trees_dash_feature_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            (repo / "trees-feature-c" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees-feature-c" / "2").mkdir(parents=True, exist_ok=True)
            (repo / "trees-feature-d" / "5").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            projects = discover_tree_projects(repo, "trees")
            names = [name for name, _root in projects]

            self.assertIn("feature-a-1", names)
            self.assertIn("feature-c-1", names)
            self.assertIn("feature-c-2", names)
            self.assertIn("feature-d-5", names)

    def test_discovers_flat_feature_roots_for_nested_trees_dir_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            (repo / "work" / "trees-feature-c" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "work" / "trees-feature-c" / "2").mkdir(parents=True, exist_ok=True)
            (repo / "work" / "trees-feature-d" / "5").mkdir(parents=True, exist_ok=True)
            (repo / "work" / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            projects = discover_tree_projects(repo, "work/trees")
            names = [name for name, _root in projects]

            self.assertIn("feature-a-1", names)
            self.assertIn("feature-c-1", names)
            self.assertIn("feature-c-2", names)
            self.assertIn("feature-d-5", names)
            self.assertNotIn("1", names)
            self.assertNotIn("2", names)
            self.assertNotIn("5", names)


if __name__ == "__main__":
    unittest.main()
