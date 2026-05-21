from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from envctl_engine.planning import discover_tree_projects, predict_plan_projects
from envctl_engine.planning.worktree_creation_commands import worktree_branch_name
from envctl_engine.planning.worktree_identity import worktree_project_name
from envctl_engine.runtime.ensure_worktree_support import _print_ensure_worktree_success


class WorktreeIdentityTests(unittest.TestCase):
    def test_branch_name_and_project_name_share_one_identity(self) -> None:
        self.assertEqual(worktree_project_name(feature="feature-a", iteration="2"), "feature-a-2")
        self.assertEqual(
            worktree_branch_name(feature="feature-a", iteration="2"),
            worktree_project_name(feature="feature-a", iteration="2"),
        )

    def test_discovery_and_predictions_use_branch_identical_project_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            (repo / "trees" / "feature-a" / "2" / "backend").mkdir(parents=True)

            projects = discover_tree_projects(repo, "trees")
            predictions = predict_plan_projects(
                projects=projects,
                plan_counts={"work/task.md": 1},  # type: ignore[arg-type]
                base_dir=repo,
                trees_dir_name="trees",
            )

        self.assertEqual(projects[0][0], worktree_branch_name(feature="feature-a", iteration="2"))
        self.assertEqual(predictions[0].name, worktree_branch_name(feature="work_task", iteration="1"))

    def test_ensure_worktree_success_reports_identical_project_and_branch_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo" / "trees" / "feature-a" / "2"
            root.mkdir(parents=True)
            payloads: list[str] = []

            import contextlib
            import io
            import json

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = _print_ensure_worktree_success(
                    feature="feature-a",
                    iteration="2",
                    worktree_root=root,
                    branch_name=worktree_branch_name(feature="feature-a", iteration="2"),
                    action="reuse",
                    existed_before=True,
                    created=False,
                    dry_run=True,
                    json_output=True,
                )
            payloads.append(stdout.getvalue())

        self.assertEqual(code, 0)
        payload = json.loads(payloads[0])
        self.assertEqual(payload["project_name"], payload["branch_name"])
        self.assertEqual(payload["project_name"], worktree_project_name(feature="feature-a", iteration="2"))


if __name__ == "__main__":
    unittest.main()
