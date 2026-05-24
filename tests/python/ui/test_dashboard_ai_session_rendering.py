from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from envctl_engine.ui.dashboard.ai_session_rendering import (
    _dashboard_path_matches_project_root,
    _dashboard_session_matches_project_root,
    dashboard_current_tmux_target,
    dashboard_repo_root_for_project,
)


class DashboardAiSessionRenderingTests(unittest.TestCase):
    def test_repo_root_prefers_worktree_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = Path(tmpdir) / "repo" / "trees" / "feature" / "1"
            repo.joinpath(".git").mkdir(parents=True)
            worktree.joinpath(".envctl-state").mkdir(parents=True)
            worktree.joinpath(".envctl-state", "worktree-provenance.json").write_text(
                f'{{"created_from_repo": "{repo}"}}',
                encoding="utf-8",
            )

            actual = dashboard_repo_root_for_project(project_root=worktree)
            self.assertEqual(actual, repo.resolve(strict=False))

    def test_session_path_matching_handles_deleted_suffix_and_nested_paths(self) -> None:
        project_root = Path("/tmp/repo/trees/feature/1")
        self.assertTrue(
            _dashboard_path_matches_project_root(
                project_root=project_root,
                candidate_path="/tmp/repo/trees/feature/1/backend (deleted)",
            )
        )
        self.assertTrue(
            _dashboard_session_matches_project_root(
                project_root=project_root,
                session={"paths": "/tmp/other\n/tmp/repo/trees/feature/1/frontend\n"},
            )
        )
        self.assertFalse(
            _dashboard_path_matches_project_root(
                project_root=project_root,
                candidate_path="/tmp/repo/trees/feature/10",
            )
        )

    def test_current_tmux_target_requires_session_and_path_lines(self) -> None:
        subprocess_module = SimpleNamespace(
            run=lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="session-a\n/tmp/repo\n")
        )

        self.assertEqual(
            dashboard_current_tmux_target(subprocess_module=subprocess_module),
            ("session-a", "/tmp/repo"),
        )

        failing_module = SimpleNamespace(run=lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""))
        self.assertEqual(dashboard_current_tmux_target(subprocess_module=failing_module), ("", ""))


if __name__ == "__main__":
    unittest.main()
