from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from envctl_engine.planning.worktree_creation_recovery import (
    recover_partial_worktree_creation,
    setup_worktree_placeholder_fallback_enabled,
    worktree_add_failure,
    worktree_target_created,
)


class WorktreeCreationRecoveryTests(unittest.TestCase):
    def test_setup_worktree_placeholder_fallback_enabled_prefers_env_over_config(self) -> None:
        self.assertTrue(
            setup_worktree_placeholder_fallback_enabled(
                env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "yes"},
                config_raw={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "false"},
            )
        )
        self.assertFalse(
            setup_worktree_placeholder_fallback_enabled(
                env={},
                config_raw={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "false"},
            )
        )

    def test_worktree_target_created_requires_directory_with_git_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"

            self.assertFalse(worktree_target_created(target))

            target.mkdir()
            self.assertFalse(worktree_target_created(target))

            (target / ".git").write_text("gitdir: /tmp/worktree\n", encoding="utf-8")
            self.assertTrue(worktree_target_created(target))

    def test_recover_partial_worktree_creation_requires_disabled_hooks_and_git_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            result = subprocess.CompletedProcess(args=["git"], returncode=1, stdout="", stderr="hook failed")
            events: list[tuple[str, dict[str, object]]] = []

            self.assertFalse(
                recover_partial_worktree_creation(
                    git_hooks_disabled=False,
                    target=target,
                    feature="feature-a",
                    iteration="1",
                    result=result,
                    command_result_error_text=lambda _result: "hook failed",
                    emit=lambda event, **payload: events.append((event, payload)),
                )
            )

            target.mkdir()
            (target / ".git").write_text("gitdir: /tmp/worktree\n", encoding="utf-8")

            self.assertTrue(
                recover_partial_worktree_creation(
                    git_hooks_disabled=True,
                    target=target,
                    feature="feature-a",
                    iteration="1",
                    result=result,
                    command_result_error_text=lambda _result: "hook failed",
                    emit=lambda event, **payload: events.append((event, payload)),
                )
            )
            self.assertEqual(events[0][0], "setup.worktree.partial_git_failure_recovered")
            self.assertEqual(events[0][1]["feature"], "feature-a")
            self.assertEqual(events[0][1]["iteration"], "1")
            self.assertEqual(events[0][1]["reason"], "hook failed")

    def test_worktree_add_failure_creates_placeholder_and_links_artifacts_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            result = subprocess.CompletedProcess(args=["git"], returncode=1, stdout="", stderr="git failure")
            linked_targets: list[Path] = []
            events: list[tuple[str, dict[str, object]]] = []

            error = worktree_add_failure(
                feature="feature-a",
                iteration="1",
                target=target,
                result=result,
                placeholder_fallback_enabled=True,
                command_result_error_text=lambda _result: "git failure",
                link_repo_local_shared_artifacts=lambda linked_target: linked_targets.append(linked_target),
                emit=lambda event, **payload: events.append((event, payload)),
            )

            self.assertIsNone(error)
            self.assertEqual(linked_targets, [target])
            self.assertEqual(events[0][0], "setup.worktree.placeholder_fallback")
            self.assertEqual(events[0][1]["reason"], "git failure")
            self.assertEqual(
                (target / ".envctl_worktree_placeholder").read_text(encoding="utf-8"),
                (
                    "envctl placeholder worktree created after git worktree add failure\n"
                    "feature=feature-a\n"
                    "iteration=1\n"
                    "error=git failure\n"
                ),
            )

    def test_worktree_add_failure_reports_target_status_and_hook_policy_hint_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target"
            result = subprocess.CompletedProcess(args=["git"], returncode=1, stdout="", stderr="git failure")

            missing_error = worktree_add_failure(
                feature="feature-a",
                iteration="1",
                target=target,
                result=result,
                placeholder_fallback_enabled=False,
                command_result_error_text=lambda _result: "git failure",
                link_repo_local_shared_artifacts=lambda _target: None,
                emit=lambda _event, **_payload: None,
            )
            target.mkdir()
            existing_error = worktree_add_failure(
                feature="feature-a",
                iteration="1",
                target=target,
                result=result,
                placeholder_fallback_enabled=False,
                command_result_error_text=lambda _result: "git failure",
                link_repo_local_shared_artifacts=lambda _target: None,
                emit=lambda _event, **_payload: None,
            )

            self.assertIn("failed creating worktree feature-a/1: git failure (target missing)", missing_error or "")
            self.assertIn("failed creating worktree feature-a/1: git failure (target exists)", existing_error or "")
            self.assertIn("ENVCTL_WORKTREE_GIT_HOOKS=inherit", existing_error or "")


if __name__ == "__main__":
    unittest.main()
