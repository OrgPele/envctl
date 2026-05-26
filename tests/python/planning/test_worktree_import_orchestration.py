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
    def _runtime(
        self,
        base_dir: Path,
        *,
        events: list[tuple[str, dict[str, object]]] | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            config=SimpleNamespace(base_dir=base_dir, trees_dir_name="trees", raw={}),
            env={},
            process_runner=SimpleNamespace(run=subprocess.run),
            _command_env=lambda *, port, extra=None: dict(os.environ, **dict(extra or {})),
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


if __name__ == "__main__":
    unittest.main()
