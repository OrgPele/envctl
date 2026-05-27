from __future__ import annotations

import tempfile
import unittest
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.planning import discover_tree_projects


class DiscoveryTopologyTests(unittest.TestCase):
    def _init_repo(self, repo: Path) -> None:
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
        (repo / "README.md").write_text("# repo\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    def assert_discovers_only_good_feature_with_stale_artifacts(self, artifact_dirs: list[str]) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            trees = repo / "trees"
            (trees / "good-feature" / "1" / "backend").mkdir(parents=True, exist_ok=True)
            for artifact_dir in artifact_dirs:
                (trees / "stale-feature" / "1" / artifact_dir).mkdir(parents=True, exist_ok=True)

            projects = discover_tree_projects(repo, "trees")

            self.assertEqual([name for name, _root in projects], ["good-feature-1"])

    def test_prefers_nested_feature_iteration_roots_over_app_leaf_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            trees = repo / "trees"
            (trees / "feature-a" / "1" / "backend" / "src").mkdir(parents=True, exist_ok=True)
            (trees / "feature-a" / "1" / "frontend" / "src").mkdir(parents=True, exist_ok=True)
            (trees / "feature-a" / "2" / "backend").mkdir(parents=True, exist_ok=True)
            (trees / "feature-b" / "1" / "package.json").parent.mkdir(parents=True, exist_ok=True)
            (trees / "feature-b" / "1" / "package.json").write_text("{}\n", encoding="utf-8")
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
            (trees / "feature-z" / "2" / "backend").mkdir(parents=True, exist_ok=True)
            (trees / "feature-z" / "1" / "backend").mkdir(parents=True, exist_ok=True)
            (trees / "feature-a" / "1" / "backend").mkdir(parents=True, exist_ok=True)

            first = discover_tree_projects(repo, "trees")
            second = discover_tree_projects(repo, "trees")

            self.assertEqual(first, second)
            self.assertEqual([name for name, _ in first], ["feature-a-1", "feature-z-1", "feature-z-2"])

    def test_ignores_omx_only_stale_iteration_dirs(self) -> None:
        self.assert_discovers_only_good_feature_with_stale_artifacts([".omx"])

    def test_ignores_envctl_state_only_stale_iteration_dirs(self) -> None:
        self.assert_discovers_only_good_feature_with_stale_artifacts([".envctl-state"])

    def test_ignores_state_only_stale_iteration_dirs_with_multiple_artifact_dirs(self) -> None:
        self.assert_discovers_only_good_feature_with_stale_artifacts([".omx", ".envctl-state"])

    def test_discovers_flat_trees_dash_feature_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            (repo / "trees-feature-c" / "1" / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "trees-feature-c" / "2" / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "trees-feature-d" / "5" / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1" / "backend").mkdir(parents=True, exist_ok=True)

            projects = discover_tree_projects(repo, "trees")
            names = [name for name, _root in projects]

            self.assertIn("feature-a-1", names)
            self.assertIn("feature-c-1", names)
            self.assertIn("feature-c-2", names)
            self.assertIn("feature-d-5", names)

    def test_discovers_flat_feature_roots_for_nested_trees_dir_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            (repo / "work" / "trees-feature-c" / "1" / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "work" / "trees-feature-c" / "2" / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "work" / "trees-feature-d" / "5" / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "work" / "trees" / "feature-a" / "1" / "backend").mkdir(parents=True, exist_ok=True)

            projects = discover_tree_projects(repo, "work/trees")
            names = [name for name, _root in projects]

            self.assertIn("feature-a-1", names)
            self.assertIn("feature-c-1", names)
            self.assertIn("feature-c-2", names)
            self.assertIn("feature-d-5", names)
            self.assertNotIn("1", names)
            self.assertNotIn("2", names)
            self.assertNotIn("5", names)

    def test_discovers_imported_branch_worktrees_individually(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            self._init_repo(repo)
            imported = repo / "trees" / "imported"
            alpha = imported / "features-ai-answer-reliability-foundation"
            beta = imported / "backend-runtime-cleanup"
            subprocess.run(
                ["git", "worktree", "add", "-q", "-b", "features_ai_answer_reliability_foundation-2", str(alpha)],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "worktree", "add", "-q", "-b", "backend_runtime_cleanup-4", str(beta)],
                cwd=repo,
                check=True,
            )

            projects = discover_tree_projects(repo, "trees")

        self.assertIn(("features_ai_answer_reliability_foundation-2", alpha), projects)
        self.assertIn(("backend_runtime_cleanup-4", beta), projects)
        self.assertNotIn(("imported", imported), projects)

    def test_discovers_imported_branch_worktree_with_slash_branch_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            self._init_repo(repo)
            imported = repo / "trees" / "imported"
            child = imported / "vk-8e38-production-secre"
            subprocess.run(
                ["git", "worktree", "add", "-q", "-b", "vk/8e38-production-secre", str(child)],
                cwd=repo,
                check=True,
            )

            projects = discover_tree_projects(repo, "trees")

        self.assertIn(("vk/8e38-production-secre", child), projects)
        self.assertNotIn(("vk-8e38-production-secre", child), projects)


if __name__ == "__main__":
    unittest.main()
