from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from envctl_engine.planning.worktree_shared_artifacts import link_repo_local_shared_artifacts


class WorktreeSharedArtifactsTests(unittest.TestCase):
    def test_link_repo_local_shared_artifacts_links_existing_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            target = repo_root / "trees" / "feature-a" / "1"
            (repo_root / "backend" / "venv").mkdir(parents=True)
            (repo_root / "backend" / ".env").write_text("DATABASE_URL=postgres://local\n", encoding="utf-8")
            (repo_root / "frontend" / "node_modules").mkdir(parents=True)
            target.mkdir(parents=True)

            link_repo_local_shared_artifacts(repo_root=repo_root, target=target)

            self.assertEqual((target / "backend" / "venv").resolve(), (repo_root / "backend" / "venv").resolve())
            self.assertEqual((target / "backend" / ".env").resolve(), (repo_root / "backend" / ".env").resolve())
            self.assertEqual(
                (target / "frontend" / "node_modules").resolve(),
                (repo_root / "frontend" / "node_modules").resolve(),
            )

    def test_link_repo_local_shared_artifacts_skips_missing_target_and_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            missing_target = repo_root / "trees" / "feature-a" / "1"
            repo_root.mkdir()

            link_repo_local_shared_artifacts(repo_root=repo_root, target=missing_target)

            self.assertFalse((missing_target / "backend").exists())
            self.assertFalse((repo_root / "backend").exists())

    def test_link_repo_local_shared_artifacts_preserves_existing_real_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            target = repo_root / "trees" / "feature-a" / "1"
            (repo_root / "backend" / "venv").mkdir(parents=True)
            (target / "backend").mkdir(parents=True)
            (target / "backend" / "venv").write_text("local worktree artifact\n", encoding="utf-8")

            link_repo_local_shared_artifacts(repo_root=repo_root, target=target)

            self.assertFalse((target / "backend" / "venv").is_symlink())
            self.assertEqual(
                (target / "backend" / "venv").read_text(encoding="utf-8"),
                "local worktree artifact\n",
            )

    def test_link_repo_local_shared_artifacts_replaces_stale_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            target = repo_root / "trees" / "feature-a" / "1"
            stale_source = Path(tmpdir) / "old-venv"
            fresh_source = repo_root / "backend" / "venv"
            stale_source.mkdir()
            fresh_source.mkdir(parents=True)
            (target / "backend").mkdir(parents=True)
            (target / "backend" / "venv").symlink_to(stale_source)

            link_repo_local_shared_artifacts(repo_root=repo_root, target=target)

            self.assertEqual((target / "backend" / "venv").resolve(), fresh_source.resolve())

    def test_link_repo_local_shared_artifacts_ignores_symlink_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            target = repo_root / "trees" / "feature-a" / "1"
            (repo_root / "backend" / "venv").mkdir(parents=True)
            target.mkdir(parents=True)

            with patch.object(Path, "symlink_to", side_effect=OSError("read-only")):
                link_repo_local_shared_artifacts(repo_root=repo_root, target=target)

            self.assertFalse((target / "backend" / "venv").exists())


if __name__ == "__main__":
    unittest.main()
