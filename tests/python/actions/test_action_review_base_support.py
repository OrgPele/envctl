from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from envctl_engine.actions import action_review_base_support as support


class ActionReviewBaseSupportTests(unittest.TestCase):
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

    def test_resolve_review_base_raises_clear_error_for_unresolvable_explicit_base(self) -> None:
        context = SimpleNamespace(
            repo_root=Path("/repo"),
            project_root=Path("/repo"),
            project_name="Main",
            env={"ENVCTL_REVIEW_BASE": "missing"},
        )

        with self.assertRaisesRegex(support.ReviewBaseResolutionError, "missing"):
            support.resolve_review_base(
                context,
                Path("/repo"),
                detect_default_branch_fn=lambda _root: "main",
                git_output_fn=lambda _root, _args: "",
            )


if __name__ == "__main__":
    unittest.main()
