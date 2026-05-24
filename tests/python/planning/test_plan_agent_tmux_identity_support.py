from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree
from envctl_engine.planning.plan_agent.tmux_identity_support import (
    next_available_tmux_session_name,
    tmux_session_name_for_worktree,
    tmux_window_name_for_worktree,
)


class PlanAgentTmuxIdentitySupportTests(unittest.TestCase):
    def test_tmux_session_name_includes_repo_relative_worktree_and_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "envctl"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="feature-a.md")

            session = tmux_session_name_for_worktree(repo, worktree, cli="OpenCode")

        self.assertEqual(session, "envctl-envctl-trees-feature-a-1-opencode")

    def test_tmux_window_name_uses_worktree_tab_title(self) -> None:
        worktree = CreatedPlanWorktree(
            name="feature/very long task name",
            root=Path("/repo/trees/feature/1"),
            plan_file="feature.md",
        )

        self.assertEqual(tmux_window_name_for_worktree(worktree), "feature-very-long-task-name")

    def test_next_available_tmux_session_name_keeps_base_when_free(self) -> None:
        with mock.patch(
            "envctl_engine.planning.plan_agent.tmux_identity_support._tmux_session_exists",
            return_value=False,
        ) as exists:
            session = next_available_tmux_session_name(SimpleNamespace(), "envctl-session")

        self.assertEqual(session, "envctl-session")
        exists.assert_called_once_with(mock.ANY, "envctl-session")

    def test_next_available_tmux_session_name_appends_first_free_suffix(self) -> None:
        occupied = {"envctl-session", "envctl-session-2"}

        def exists(_runtime: object, session_name: str) -> bool:
            return session_name in occupied

        with mock.patch(
            "envctl_engine.planning.plan_agent.tmux_identity_support._tmux_session_exists",
            side_effect=exists,
        ):
            session = next_available_tmux_session_name(SimpleNamespace(), "envctl-session")

        self.assertEqual(session, "envctl-session-3")


if __name__ == "__main__":
    unittest.main()
