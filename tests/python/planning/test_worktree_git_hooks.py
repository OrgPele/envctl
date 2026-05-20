from __future__ import annotations

from types import SimpleNamespace
import unittest

from envctl_engine.planning.worktree_git_hooks import (
    worktree_git_hooks_disabled,
    worktree_git_hooks_policy,
)


class WorktreeGitHooksTests(unittest.TestCase):
    def _engine(self, *, env: dict[str, str] | None = None, raw: dict[str, str] | None = None) -> object:
        return SimpleNamespace(env=env or {}, config=SimpleNamespace(raw=raw or {}))

    def test_git_hooks_are_disabled_by_default(self) -> None:
        engine = self._engine()

        self.assertEqual(worktree_git_hooks_policy(engine), "disabled")
        self.assertTrue(worktree_git_hooks_disabled(engine))

    def test_env_policy_wins_over_config_policy(self) -> None:
        engine = self._engine(env={"ENVCTL_WORKTREE_GIT_HOOKS": "inherit"}, raw={"ENVCTL_WORKTREE_GIT_HOOKS": "off"})

        self.assertEqual(worktree_git_hooks_policy(engine), "inherit")
        self.assertFalse(worktree_git_hooks_disabled(engine))

    def test_invalid_policy_fails_closed_with_allowed_values(self) -> None:
        engine = self._engine(env={"ENVCTL_WORKTREE_GIT_HOOKS": "maybe"})

        with self.assertRaisesRegex(RuntimeError, "ENVCTL_WORKTREE_GIT_HOOKS"):
            worktree_git_hooks_policy(engine)


if __name__ == "__main__":
    unittest.main()
