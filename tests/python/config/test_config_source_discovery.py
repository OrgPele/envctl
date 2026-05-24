from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from envctl_engine.config import _generated_worktree_control_root, _parse_envctl_text, discover_local_config_state
from envctl_engine.config.source_discovery import (
    control_root_from_generated_tree_shape,
    control_root_from_worktree_provenance,
    generated_worktree_control_root,
    parse_envctl_text,
)


class ConfigSourceDiscoveryTests(unittest.TestCase):
    def test_parse_envctl_text_ignores_comments_exports_quotes_and_template_sections(self) -> None:
        text = """
        # comment
        export BACKEND_DIR="api"
        FRONTEND_DIR='web'
        NO_VALUE
        # >>> envctl dependency env >>>
        DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}
        # <<< envctl dependency env <<<
        """

        self.assertEqual(parse_envctl_text(text), {"BACKEND_DIR": "api", "FRONTEND_DIR": "web"})
        self.assertEqual(_parse_envctl_text(text), {"BACKEND_DIR": "api", "FRONTEND_DIR": "web"})

    def test_discover_local_config_state_prefers_primary_envctl_over_legacy_prefill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".envctl").write_text("BACKEND_DIR=api\n", encoding="utf-8")
            (repo / ".envctl.sh").write_text("BACKEND_DIR=legacy\n", encoding="utf-8")

            state = discover_local_config_state(repo)

            self.assertEqual(state.config_source, "envctl")
            self.assertEqual(state.active_source_path, (repo / ".envctl").resolve())
            self.assertIsNone(state.legacy_source_path)
            self.assertEqual(state.parsed_values["BACKEND_DIR"], "api")

    def test_discover_local_config_state_uses_explicit_legacy_prefill_without_primary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            legacy = repo / "custom.env"
            legacy.write_text("FRONTEND_DIR=ui\n", encoding="utf-8")

            state = discover_local_config_state(repo, "custom.env")

            self.assertEqual(state.config_source, "legacy_prefill")
            self.assertEqual(state.active_source_path, legacy.resolve())
            self.assertEqual(state.legacy_source_path, legacy.resolve())
            self.assertEqual(state.config_file_path, (repo / ".envctl").resolve())
            self.assertFalse(state.config_file_exists)
            self.assertEqual(state.parsed_values["FRONTEND_DIR"], "ui")

    def test_control_root_from_worktree_provenance_requires_existing_parent_envctl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            worktree = root / "trees" / "feature" / "1"
            (repo).mkdir()
            (repo / ".envctl").write_text("BACKEND_DIR=api\n", encoding="utf-8")
            (worktree / ".envctl-state").mkdir(parents=True)
            (worktree / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps({"created_from_repo": str(repo)}),
                encoding="utf-8",
            )

            self.assertEqual(control_root_from_worktree_provenance(worktree), repo.resolve())

            (repo / ".envctl").unlink()
            self.assertIsNone(control_root_from_worktree_provenance(worktree))

    def test_generated_tree_shape_uses_parent_envctl_until_git_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            worktree = repo / "trees" / "feature" / "2"
            nested = worktree / "nested"
            nested.mkdir(parents=True)
            (repo / ".envctl").write_text("BACKEND_DIR=api\n", encoding="utf-8")

            self.assertEqual(control_root_from_generated_tree_shape(nested, trees_dir_name="trees"), repo.resolve())
            self.assertEqual(
                generated_worktree_control_root(
                    requested_root=nested,
                    execution_root=nested,
                    trees_dir_name="trees",
                ),
                repo.resolve(),
            )
            self.assertEqual(
                _generated_worktree_control_root(
                    requested_root=nested,
                    execution_root=nested,
                    trees_dir_name="trees",
                ),
                repo.resolve(),
            )

            unrelated = root / "other"
            (unrelated / ".git").mkdir(parents=True)
            self.assertIsNone(control_root_from_generated_tree_shape(unrelated, trees_dir_name="trees"))


if __name__ == "__main__":
    unittest.main()
