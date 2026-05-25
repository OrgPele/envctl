from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

from envctl_engine.actions import action_review_base_support as base_support
from envctl_engine.actions import action_review_iteration_support as support
from envctl_engine.actions import action_review_original_plan_support as original_plan_support


class ActionReviewIterationSupportTests(unittest.TestCase):
    def test_analysis_iterations_selects_current_tree_for_single_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            family = Path(tmpdir) / "feature"
            project_root = family / "2"
            for name in ("1", "2", "3"):
                child = family / name
                child.mkdir(parents=True)
                (child / ".git").write_text("gitdir: /tmp/tree\n", encoding="utf-8")
            context = SimpleNamespace(repo_root=Path(tmpdir) / "repo", project_root=project_root)

            self.assertEqual(support.analysis_iterations(context, mode="single"), ["2"])
            self.assertEqual(support.analysis_iterations(context, mode="grouped"), ["1", "2", "3"])

    def test_run_analyze_helper_augments_and_prunes_review_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo_root = root / "repo"
            project_root = repo_root / "trees" / "feature" / "1"
            project_root.mkdir(parents=True)
            (project_root / ".git").write_text("gitdir: /tmp/feature\n", encoding="utf-8")
            plan = repo_root / "todo" / "plans" / "features" / "example.md"
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan\n", encoding="utf-8")
            tree_diffs_root = root / "tree-diffs"
            context = SimpleNamespace(
                repo_root=repo_root,
                project_root=project_root,
                project_name="feature-1",
                env={"ENVCTL_ACTION_TREE_DIFFS_ROOT": str(tree_diffs_root)},
                interactive=False,
            )
            seen_env: dict[str, str] = {}

            def fake_run(args: list[str], **kwargs):  # noqa: ANN001
                seen_env.update({str(key): str(value) for key, value in (kwargs.get("env") or {}).items()})
                output_dir = Path(next(token.split("=", 1)[1] for token in args if token.startswith("output-dir=")))
                output_dir.mkdir(parents=True)
                (output_dir / "summary.md").write_text("# Summary\n", encoding="utf-8")
                (output_dir / "all.md").write_text("# Full\n", encoding="utf-8")
                (output_dir / "prompt.md").write_text("delete me\n", encoding="utf-8")
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

            code = support.run_analyze_helper(
                context=context,
                helper=repo_root / "utils" / "analyze-tree-changes.sh",
                iterations=["1"],
                mode="single",
                scope="all",
                review_base=base_support.ReviewBaseResolution(
                    base_branch="main",
                    base_ref="origin/main",
                    source="provenance",
                    merge_base="merge-base",
                ),
                original_plan=original_plan_support.OriginalPlanResolution(path=plan, source="provenance"),
                sanitize_label_fn=lambda value: value.replace("/", "_"),
                run_process_fn=fake_run,
            )

            self.assertEqual(code, 0)
            self.assertEqual(seen_env["ENVCTL_REVIEW_ORIGINAL_PLAN_FILE"], str(plan))
            output_dir = next(tree_diffs_root.glob("analysis_feature-1_all_single_*"))
            self.assertFalse((output_dir / "prompt.md").exists())
            self.assertIn("## Original plan file", (output_dir / "all.md").read_text(encoding="utf-8"))
            self.assertIn("## Original plan resolution", (output_dir / "summary.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
