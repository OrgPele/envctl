from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

from envctl_engine.actions import action_review_plan_support as support


class ActionReviewPlanSupportTests(unittest.TestCase):
    def test_resolve_original_plan_prefers_worktree_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            project_root = repo_root / "trees" / "feature" / "1"
            project_root.mkdir(parents=True)
            provenance = project_root / ".envctl-state" / "worktree-provenance.json"
            provenance.parent.mkdir()
            provenance.write_text('{"schema_version": 1, "plan_file": "features/example.md"}', encoding="utf-8")
            plan = repo_root / "todo" / "plans" / "features" / "example.md"
            plan.parent.mkdir(parents=True)
            plan.write_text("# Example\n", encoding="utf-8")
            context = SimpleNamespace(
                repo_root=repo_root,
                project_root=project_root,
                project_name="feature-1",
                env={},
            )

            resolved = support.resolve_original_plan(context)

            self.assertEqual(resolved.path, plan.resolve())
            self.assertEqual(resolved.source, "provenance")

    def test_resolve_review_base_uses_provenance_source_ref_before_upstream(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            git_root = Path(tmpdir) / "repo"
            project_root = git_root / "trees" / "feature" / "1"
            project_root.mkdir(parents=True)
            provenance = project_root / ".envctl-state" / "worktree-provenance.json"
            provenance.parent.mkdir()
            provenance.write_text(
                '{"schema_version": 1, "source_branch": "main", "source_ref": "origin/main"}',
                encoding="utf-8",
            )
            calls: list[list[str]] = []

            def git_output(_root: Path, args: list[str]) -> str:
                calls.append(args)
                if args == ["rev-parse", "--verify", "origin/main"]:
                    return "base-ref\n"
                if args == ["merge-base", "HEAD", "origin/main"]:
                    return "merge-base\n"
                return ""

            context = SimpleNamespace(repo_root=git_root, project_root=project_root, project_name="feature-1", env={})

            resolved = support.resolve_review_base(
                context,
                git_root,
                detect_default_branch_fn=lambda _root: "develop",
                git_output_fn=git_output,
            )

            self.assertEqual(resolved.base_branch, "main")
            self.assertEqual(resolved.base_ref, "origin/main")
            self.assertEqual(resolved.source, "provenance")
            self.assertEqual(resolved.merge_base, "merge-base")
            self.assertNotIn(["rev-parse", "--abbrev-ref", "HEAD"], calls)

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
                review_base=support.ReviewBaseResolution(
                    base_branch="main",
                    base_ref="origin/main",
                    source="provenance",
                    merge_base="merge-base",
                ),
                original_plan=support.OriginalPlanResolution(path=plan, source="provenance"),
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
