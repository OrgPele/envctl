from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from envctl_engine.actions import action_review_original_plan_support as support


class ActionReviewOriginalPlanSupportTests(unittest.TestCase):
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

    def test_augment_review_markdown_file_injects_original_plan_after_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            plan = root / "plan.md"
            plan.write_text("# Plan\nBody\n", encoding="utf-8")
            summary = root / "summary.md"
            summary.write_text("# Summary\n\nResult body\n", encoding="utf-8")

            support.augment_review_markdown_file(
                summary,
                original_plan=support.OriginalPlanResolution(path=plan, source="provenance"),
                include_contents=True,
            )

            text = summary.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("# Summary\n\n## Original plan file"))
            self.assertIn("## Original plan resolution\nprovenance", text)
            self.assertIn("## Original plan\n# Plan\nBody", text)
            self.assertIn("Result body", text)


if __name__ == "__main__":
    unittest.main()
