from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree
from envctl_engine.planning.worktree_import_orchestration import import_remote_branch_worktree


class WorktreeImportOrchestrationTests(unittest.TestCase):
    def _repo_with_remote_feature_branch(self, root: Path) -> tuple[Path, Path, Path]:
        origin = root / "origin.git"
        source = root / "source"
        repo = root / "repo"
        subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
        subprocess.run(["git", "clone", str(origin), str(source)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "config", "user.email", "dev@example.test"], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "Dev"], check=True)
        (source / "README.md").write_text("main\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "main"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "push", "origin", "HEAD:main"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "switch", "-c", "feature/foo"], check=True, capture_output=True)
        (source / "feature.txt").write_text("one\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "feature.txt"], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "one"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(source), "push", "-u", "origin", "feature/foo"], check=True)
        subprocess.run(["git", "clone", str(origin), str(repo)], check=True, capture_output=True)
        return source, repo, repo / "trees" / "imported" / "feature-foo"

    def _runtime(
        self,
        base_dir: Path,
        *,
        events: list[tuple[str, dict[str, object]]] | None = None,
        command_env=None,
        runner=None,
    ) -> SimpleNamespace:
        def default_command_env(*, port, extra=None):
            return dict(os.environ, **dict(extra or {}))

        return SimpleNamespace(
            config=SimpleNamespace(base_dir=base_dir, trees_dir_name="trees", raw={}),
            env={},
            process_runner=SimpleNamespace(run=runner or subprocess.run),
            _command_env=command_env or default_command_env,
            _emit=lambda event, **payload: events.append((event, payload)) if events is not None else None,
        )

    def test_import_remote_branch_creates_managed_worktree_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            origin = root / "origin.git"
            source = root / "source"
            repo = root / "repo"
            subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
            subprocess.run(["git", "clone", str(origin), str(source)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "config", "user.email", "dev@example.test"], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "Dev"], check=True)
            (source / "README.md").write_text("main\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-m", "main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "push", "origin", "HEAD:main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "switch", "-c", "feature/foo"], check=True, capture_output=True)
            (source / "feature.txt").write_text("remote\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "feature.txt"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-m", "feature"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "push", "-u", "origin", "feature/foo"], check=True)
            subprocess.run(["git", "clone", str(origin), str(repo)], check=True, capture_output=True)

            events: list[tuple[str, dict[str, object]]] = []
            runtime = self._runtime(repo, events=events)
            with (
                patch(
                    "envctl_engine.planning.worktree_import_orchestration.link_repo_local_shared_artifacts"
                ) as link_artifacts,
                patch(
                    "envctl_engine.planning.worktree_import_orchestration.prepare_worktree_code_intelligence"
                ) as prepare_code,
            ):
                result = import_remote_branch_worktree(runtime, branch_input="origin/feature/foo")

            self.assertIsNone(result.error)
            self.assertEqual(len(result.created_worktrees), 1)
            created = result.created_worktrees[0]
            self.assertIsInstance(created, CreatedPlanWorktree)
            self.assertEqual(created.name, "feature-foo")
            self.assertEqual(created.plan_file, "")
            self.assertTrue((created.root / "feature.txt").is_file())
            link_artifacts.assert_called_once_with(repo_root=repo, target=created.root)
            prepare_code.assert_called_once()

            self.assertEqual(
                subprocess.run(
                    ["git", "-C", str(created.root), "config", "--get", "branch.feature/foo.remote"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip(),
                "origin",
            )
            self.assertEqual(
                subprocess.run(
                    ["git", "-C", str(created.root), "config", "--get", "branch.feature/foo.merge"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip(),
                "refs/heads/feature/foo",
            )
            subprocess.run(["git", "-C", str(created.root), "pull", "--ff-only"], check=True, capture_output=True)

            provenance_path = created.root / ".envctl-state" / "worktree-provenance.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            self.assertEqual(provenance["resolution_reason"], "remote_branch_import")
            self.assertEqual(provenance["imported_branch"], "feature/foo")
            self.assertEqual(provenance["import_remote"], "origin")
            self.assertEqual(provenance["remote_ref"], "origin/feature/foo")
            self.assertEqual(
                subprocess.run(
                    ["git", "-C", str(created.root), "status", "--short", "--untracked-files=all"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout,
                "",
            )
            self.assertEqual(result.raw_projects, [("feature-foo", created.root)])
            event_names = [event for event, _payload in events]
            self.assertEqual(
                event_names,
                [
                    "planning.import.normalized",
                    "planning.import.fetch.start",
                    "planning.import.fetch.result",
                    "planning.import.worktree.create.start",
                    "planning.import.worktree.create.result",
                    "planning.import.update.start",
                    "planning.import.update.result",
                    "planning.import.provenance.write",
                    "planning.import.ready",
                ],
            )
            self.assertEqual(events[2][1]["returncode"], 0)
            self.assertEqual(events[4][1]["returncode"], 0)
            self.assertEqual(events[6][1]["returncode"], 0)
            self.assertEqual(events[-1][1]["local_branch"], "feature/foo")
            self.assertEqual(events[-1][1]["remote_ref"], "origin/feature/foo")

    def test_import_remote_branch_reuses_existing_worktree_with_ff_only_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            origin = root / "origin.git"
            source = root / "source"
            repo = root / "repo"
            subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
            subprocess.run(["git", "clone", str(origin), str(source)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "config", "user.email", "dev@example.test"], check=True)
            subprocess.run(["git", "-C", str(source), "config", "user.name", "Dev"], check=True)
            (source / "README.md").write_text("main\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-m", "main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "push", "origin", "HEAD:main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "switch", "-c", "feature/foo"], check=True, capture_output=True)
            (source / "feature.txt").write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "feature.txt"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-m", "one"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "push", "-u", "origin", "feature/foo"], check=True)
            subprocess.run(["git", "clone", str(origin), str(repo)], check=True, capture_output=True)

            events: list[tuple[str, dict[str, object]]] = []
            runtime = self._runtime(repo, events=events)
            with (
                patch("envctl_engine.planning.worktree_import_orchestration.link_repo_local_shared_artifacts"),
                patch("envctl_engine.planning.worktree_import_orchestration.prepare_worktree_code_intelligence"),
            ):
                first = import_remote_branch_worktree(runtime, branch_input="feature/foo")
            self.assertIsNone(first.error)
            target = first.created_worktrees[0].root

            (source / "feature.txt").write_text("two\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "feature.txt"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-m", "two"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "push"], check=True)

            with (
                patch("envctl_engine.planning.worktree_import_orchestration.link_repo_local_shared_artifacts"),
                patch("envctl_engine.planning.worktree_import_orchestration.prepare_worktree_code_intelligence"),
            ):
                second = import_remote_branch_worktree(runtime, branch_input="feature/foo")

            self.assertIsNone(second.error)
            self.assertEqual(second.created_worktrees[0].root, target)
            self.assertEqual((target / "feature.txt").read_text(encoding="utf-8"), "two\n")
            event_names = [event for event, _payload in events]
            self.assertIn("planning.import.worktree.reuse", event_names)
            self.assertEqual(events[-1][1]["action"], "reused")

    def test_import_remote_branch_fetch_failure_emits_actionable_failure_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            origin = root / "origin.git"
            repo = root / "repo"
            subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
            subprocess.run(["git", "clone", str(origin), str(repo)], check=True, capture_output=True)

            events: list[tuple[str, dict[str, object]]] = []
            result = import_remote_branch_worktree(self._runtime(repo, events=events), branch_input="feature/missing")

            self.assertIsNotNone(result.error)
            assert result.error is not None
            self.assertIn("Import fetch failed", result.error)
            self.assertIn("branch=feature/missing", result.error)
            self.assertIn("remote=origin", result.error)
            self.assertIn("remote_ref=origin/feature/missing", result.error)
            self.assertFalse((repo / "trees" / "imported" / "feature-missing").exists())
            fetch_event = events[-1]
            self.assertEqual(fetch_event[0], "planning.import.fetch.result")
            self.assertNotEqual(fetch_event[1]["returncode"], 0)
            self.assertEqual(fetch_event[1]["action"], "fetch")
            self.assertEqual(fetch_event[1]["failure_reason"], "fetch_failed")
            self.assertEqual(fetch_event[1]["branch"], "feature/missing")
            self.assertEqual(fetch_event[1]["local_branch"], "feature/missing")
            self.assertEqual(fetch_event[1]["remote"], "origin")
            self.assertEqual(fetch_event[1]["remote_ref"], "origin/feature/missing")
            self.assertEqual(
                fetch_event[1]["worktree_root"],
                str((repo / "trees" / "imported" / "feature-missing").resolve()),
            )

    def test_import_remote_branch_preserves_github_tokens_for_git_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _source, repo, _target = self._repo_with_remote_feature_branch(Path(tmpdir))
            captured_fetch_envs: list[dict[str, str]] = []

            def stripped_command_env(*, port, extra=None):
                env = dict(os.environ, **dict(extra or {}))
                env.pop("GH_TOKEN", None)
                env.pop("GITHUB_TOKEN", None)
                return env

            def capturing_runner(command, **kwargs):
                env = kwargs.get("env")
                if command[:4] == ["git", "-C", str(repo), "fetch"]:
                    captured_fetch_envs.append(dict(env or {}))
                return subprocess.run(command, **kwargs)

            runtime = self._runtime(
                repo,
                command_env=stripped_command_env,
                runner=capturing_runner,
            )

            with (
                patch.dict(
                    os.environ,
                    {
                        "GH_TOKEN": "gh-secret",
                        "GITHUB_TOKEN": "github-secret",
                    },
                ),
                patch("envctl_engine.planning.worktree_import_orchestration.link_repo_local_shared_artifacts"),
                patch("envctl_engine.planning.worktree_import_orchestration.prepare_worktree_code_intelligence"),
            ):
                result = import_remote_branch_worktree(runtime, branch_input="feature/foo")

            self.assertIsNone(result.error)
            self.assertTrue(captured_fetch_envs)
            self.assertEqual(captured_fetch_envs[0]["GH_TOKEN"], "gh-secret")
            self.assertEqual(captured_fetch_envs[0]["GITHUB_TOKEN"], "github-secret")

    def test_import_remote_branch_rejects_existing_target_on_wrong_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source, repo, target = self._repo_with_remote_feature_branch(Path(tmpdir))
            events: list[tuple[str, dict[str, object]]] = []
            runtime = self._runtime(repo, events=events)
            with (
                patch("envctl_engine.planning.worktree_import_orchestration.link_repo_local_shared_artifacts"),
                patch("envctl_engine.planning.worktree_import_orchestration.prepare_worktree_code_intelligence"),
            ):
                first = import_remote_branch_worktree(runtime, branch_input="feature/foo")
            self.assertIsNone(first.error)
            subprocess.run(["git", "-C", str(target), "switch", "-c", "feature/bar"], check=True, capture_output=True)

            result = import_remote_branch_worktree(runtime, branch_input="feature/foo")

            self.assertIsNotNone(result.error)
            assert result.error is not None
            self.assertIn("Import reuse failed", result.error)
            self.assertIn("actual_branch=feature/bar", result.error)
            self.assertIn("expected_branch=feature/foo", result.error)
            self.assertEqual((target / "feature.txt").read_text(encoding="utf-8"), "one\n")
            mismatch_event = events[-1]
            self.assertEqual(mismatch_event[0], "planning.import.worktree.branch_mismatch")
            self.assertEqual(mismatch_event[1]["failure_reason"], "wrong_branch")
            self.assertEqual(mismatch_event[1]["actual_branch"], "feature/bar")
            self.assertEqual(mismatch_event[1]["expected_branch"], "feature/foo")
            self.assertEqual(mismatch_event[1]["worktree_root"], str(target.resolve()))
            self.assertTrue(source.is_dir())

    def test_import_remote_branch_classifies_local_branch_checked_out_elsewhere(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            _source, repo, target = self._repo_with_remote_feature_branch(Path(tmpdir))
            elsewhere = Path(tmpdir) / "elsewhere"
            subprocess.run(
                ["git", "-C", str(repo), "fetch", "origin", "feature/foo:refs/remotes/origin/feature/foo"], check=True
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "worktree",
                    "add",
                    "--track",
                    "-b",
                    "feature/foo",
                    str(elsewhere),
                    "origin/feature/foo",
                ],
                check=True,
                capture_output=True,
            )
            events: list[tuple[str, dict[str, object]]] = []

            result = import_remote_branch_worktree(self._runtime(repo, events=events), branch_input="feature/foo")

            self.assertIsNotNone(result.error)
            assert result.error is not None
            self.assertIn("Import worktree_add failed", result.error)
            self.assertIn("checked out in another worktree", result.error)
            self.assertFalse(target.exists())
            create_result = events[-1]
            self.assertEqual(create_result[0], "planning.import.worktree.create.result")
            self.assertNotEqual(create_result[1]["returncode"], 0)
            self.assertEqual(create_result[1]["failure_reason"], "local_branch_checked_out_elsewhere")
            self.assertEqual(create_result[1]["local_branch"], "feature/foo")

    def test_import_remote_branch_resets_diverged_worktree_to_remote(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source, repo, target = self._repo_with_remote_feature_branch(Path(tmpdir))
            events: list[tuple[str, dict[str, object]]] = []
            runtime = self._runtime(repo, events=events)
            with (
                patch("envctl_engine.planning.worktree_import_orchestration.link_repo_local_shared_artifacts"),
                patch("envctl_engine.planning.worktree_import_orchestration.prepare_worktree_code_intelligence"),
            ):
                first = import_remote_branch_worktree(runtime, branch_input="feature/foo")
            self.assertIsNone(first.error)

            subprocess.run(["git", "-C", str(target), "config", "user.email", "dev@example.test"], check=True)
            subprocess.run(["git", "-C", str(target), "config", "user.name", "Dev"], check=True)
            (target / "local.txt").write_text("local\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(target), "add", "local.txt"], check=True)
            subprocess.run(["git", "-C", str(target), "commit", "-m", "local"], check=True, capture_output=True)
            (source / "remote.txt").write_text("remote\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(source), "add", "remote.txt"], check=True)
            subprocess.run(["git", "-C", str(source), "commit", "-m", "remote"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "push"], check=True, capture_output=True)

            result = import_remote_branch_worktree(runtime, branch_input="feature/foo")

            self.assertIsNone(result.error)
            self.assertFalse((target / "local.txt").exists())
            self.assertEqual((target / "remote.txt").read_text(encoding="utf-8"), "remote\n")
            head_message = subprocess.check_output(
                ["git", "-C", str(target), "log", "-1", "--pretty=%s"],
                text=True,
            ).strip()
            self.assertEqual(head_message, "remote")
            update_result = events[-1]
            self.assertEqual(update_result[0], "planning.import.ready")
            self.assertEqual(update_result[1]["action"], "reused")


if __name__ == "__main__":
    unittest.main()
