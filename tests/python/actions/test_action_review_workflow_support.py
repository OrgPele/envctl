from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from envctl_engine.actions import action_review_plan_support as review_plan_support
from envctl_engine.actions import action_review_workflow_support as support


class ActionReviewWorkflowSupportTests(unittest.TestCase):
    def test_review_workflow_writes_based_summary_without_repo_helper(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo_root = root / "repo"
            project_root = repo_root / "trees" / "feature" / "1"
            output_root = root / "tree-diffs"
            project_root.mkdir(parents=True)
            context = SimpleNamespace(
                repo_root=repo_root,
                project_root=project_root,
                project_name="feature-1",
                env={},
                interactive=False,
            )

            def git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["diff", "--find-renames", "--stat", "merge-base"]:
                    return " app.py | 2 +-\n"
                if args == ["diff", "--find-renames", "--name-status", "merge-base"]:
                    return "M\tapp.py\n"
                if args == ["diff", "--find-renames", "merge-base"]:
                    return "diff --git a/app.py b/app.py\n"
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return " M app.py\n"
                return ""

            code = support.run_review_workflow(
                context,
                resolve_git_root_fn=lambda project_root, _repo_root: project_root,
                git_available=True,
                git_output_fn=git_output,
                resolve_analyze_mode_fn=lambda _context: "single",
                resolve_original_plan_fn=lambda _context: review_plan_support.OriginalPlanResolution(
                    path=None,
                    source="unresolved",
                ),
                resolve_review_base_fn=lambda _context, _git_root: review_plan_support.ReviewBaseResolution(
                    base_branch="main",
                    base_ref="origin/main",
                    source="default_branch",
                    merge_base="merge-base",
                ),
                analysis_iterations_fn=lambda _context, _mode: [],
                run_analyze_helper_fn=lambda *_args: self.fail("helper should not run"),
                tree_diffs_output_path_fn=lambda _context, directory, prefix: output_root / directory / f"{prefix}.md",
                original_plan_markdown_lines_fn=lambda _resolution: [
                    "## Original plan file",
                    "(unresolved)",
                    "",
                ],
                sanitize_label_fn=lambda value: value,
            )

            self.assertEqual(code, 0)
            markdown = (output_root / "review" / "review_feature-1_single.md").read_text(encoding="utf-8")
            self.assertIn("## Base branch\nmain", markdown)
            self.assertIn("## Changed files\nM\tapp.py", markdown)
            self.assertIn("## Working tree / untracked files\nM app.py", markdown)

    def test_review_workflow_reports_invalid_review_base_before_writing_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo_root = root / "repo"
            repo_root.mkdir()
            context = SimpleNamespace(
                repo_root=repo_root,
                project_root=repo_root,
                project_name="Main",
                env={"ENVCTL_REVIEW_BASE": "missing"},
                interactive=False,
            )

            code = support.run_review_workflow(
                context,
                resolve_git_root_fn=lambda project_root, _repo_root: project_root,
                git_available=True,
                git_output_fn=lambda _git_root, _args: "",
                resolve_analyze_mode_fn=lambda _context: "single",
                resolve_original_plan_fn=lambda _context: review_plan_support.OriginalPlanResolution(
                    path=None,
                    source="not_applicable",
                ),
                resolve_review_base_fn=lambda _context, _git_root: (_ for _ in ()).throw(
                    review_plan_support.ReviewBaseResolutionError("bad base")
                ),
                analysis_iterations_fn=lambda _context, _mode: [],
                run_analyze_helper_fn=lambda *_args: self.fail("helper should not run"),
                tree_diffs_output_path_fn=lambda *_args: self.fail("summary should not be written"),
                original_plan_markdown_lines_fn=lambda _resolution: [],
                sanitize_label_fn=lambda value: value,
            )

            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
