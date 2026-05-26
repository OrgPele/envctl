from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from envctl_engine.actions.action_review_artifact_support import (
    file_has_text,
    summary_output_path,
    tree_changelog_path,
    write_markdown_lines,
)


class ActionReviewArtifactSupportTests(unittest.TestCase):
    def test_write_markdown_lines_creates_parent_and_uses_newline_join(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "reports" / "review.md"

            write_markdown_lines(path, ["# Review", "", "Ready"])

            self.assertEqual(path.read_text(encoding="utf-8"), "# Review\n\nReady")

    def test_file_has_text_ignores_missing_and_blank_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            blank = root / "blank.md"
            filled = root / "filled.md"
            blank.write_text(" \n\t\n", encoding="utf-8")
            filled.write_text(" ship it\n", encoding="utf-8")

            self.assertFalse(file_has_text(root / "missing.md"))
            self.assertFalse(file_has_text(blank))
            self.assertTrue(file_has_text(filled))

    def test_tree_changelog_path_uses_main_label_for_main_and_sanitized_project_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            changelog_dir = repo_root / "docs" / "changelog"
            changelog_dir.mkdir(parents=True)
            main_changelog = changelog_dir / "main_changelog.md"
            feature_changelog = changelog_dir / "feature_x_changelog.md"
            main_changelog.write_text("# Main\n", encoding="utf-8")
            feature_changelog.write_text("# Feature\n", encoding="utf-8")

            main_context = SimpleNamespace(project_root=repo_root, project_name="Main")
            feature_context = SimpleNamespace(project_root=repo_root, project_name="feature/x")

            self.assertEqual(tree_changelog_path(main_context), main_changelog)
            self.assertEqual(tree_changelog_path(feature_context), feature_changelog)

    def test_tree_changelog_path_skips_blank_changelogs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            changelog_dir = repo_root / "docs" / "changelog"
            changelog_dir.mkdir(parents=True)
            (changelog_dir / "feature_changelog.md").write_text("\n", encoding="utf-8")
            context = SimpleNamespace(project_root=repo_root, project_name="feature")

            self.assertIsNone(tree_changelog_path(context))

    def test_summary_output_path_creates_sanitized_timestamped_artifact_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)

            path = summary_output_path(
                repo_root,
                "review",
                "report",
                label="feature/a",
            )

            self.assertEqual(path.parent, repo_root / "review")
            self.assertTrue(path.name.startswith("report_feature_a_"))
            self.assertTrue(path.name.endswith(".md"))
            self.assertTrue(path.parent.is_dir())

    def test_summary_output_path_sanitizes_prefix_and_label_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)

            path = summary_output_path(repo_root, "review", "../report", label="../feature/a")

            self.assertEqual(path.parent, repo_root / "review")
            self.assertTrue(path.name.startswith("report_feature_a_"))
            self.assertNotIn("..", path.parts)


if __name__ == "__main__":
    unittest.main()
