from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree
from envctl_engine.planning.plan_agent.workflow_code_intelligence_context import (
    CodeIntelligencePromptBuilder,
    _append_code_intelligence_context_for_preset,
)
from envctl_engine.planning.worktree_code_intelligence_models import WORKTREE_CODE_INTELLIGENCE_PATH


def _worktree(root: Path) -> CreatedPlanWorktree:
    return CreatedPlanWorktree(name="feature-a-1", root=root, plan_file="feature-a.md")


def _write_metadata(root: Path, payload: dict[str, object]) -> None:
    path = root / WORKTREE_CODE_INTELLIGENCE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


class PlanAgentWorkflowCodeIntelligenceContextTests(unittest.TestCase):
    def test_builder_renders_serena_only_when_codegraph_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            (root / ".serena").mkdir()
            (root / ".serena" / "project.yml").write_text('project_name: "repo-feature-a-1"\n', encoding="utf-8")
            _write_metadata(
                root,
                {
                    "schema_version": 1,
                    "serena_project_name": "repo-feature-a-1",
                    "files": {".serena/project.yml": True, ".cgcignore": False},
                    "cgc_index_mode": "disabled",
                    "cgc_index_requested": False,
                    "cgc_index_skipped_reason": "disabled",
                    "codegraph_index_mode": "disabled",
                    "codegraph_index_requested": False,
                    "codegraph_index_skipped_reason": "disabled",
                },
            )

            section = CodeIntelligencePromptBuilder(_worktree(root)).prompt_section()

        self.assertIn("## Worktree code intelligence", section)
        self.assertIn("Serena project `repo-feature-a-1`", section)
        self.assertIn("symbol definitions, references, call paths, and semantic edits", section)
        self.assertNotIn("CodeGraphContext", section)
        self.assertNotIn("CodeGraph index", section)
        self.assertNotIn("envctl source checkout", section)

    def test_builder_uses_existing_serena_file_when_metadata_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            (root / ".serena").mkdir(parents=True)
            (root / ".serena" / "project.yml").write_text('project_name: "actual-worktree"\n', encoding="utf-8")
            _write_metadata(
                root,
                {
                    "schema_version": 1,
                    "serena_project_name": "stale-generated-name",
                    "files": {".serena/project.yml": False, ".cgcignore": False},
                    "cgc_index_mode": "disabled",
                    "cgc_index_requested": False,
                    "cgc_index_skipped_reason": "disabled",
                },
            )

            section = CodeIntelligencePromptBuilder(_worktree(root)).prompt_section()

        self.assertIn("Serena project `actual-worktree`", section)
        self.assertNotIn("stale-generated-name", section)

    def test_builder_uses_serena_project_local_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            (root / ".serena").mkdir(parents=True)
            (root / ".serena" / "project.yml").write_text('project_name: "base"\n', encoding="utf-8")
            (root / ".serena" / "project.local.yml").write_text(
                'project_name: "generated-worktree"\n',
                encoding="utf-8",
            )
            _write_metadata(
                root,
                {
                    "schema_version": 1,
                    "serena_project_name": "metadata-name",
                    "files": {".serena/project.local.yml": True},
                },
            )

            section = CodeIntelligencePromptBuilder(_worktree(root)).prompt_section()

        self.assertIn("Serena project `generated-worktree`", section)
        self.assertNotIn("metadata-name", section)
        self.assertNotIn("Serena project `base`", section)

    def test_builder_adds_envctl_source_checkout_hint_only_for_envctl_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            (root / "bin").mkdir(parents=True)
            (root / "bin" / "envctl").write_text("#!/bin/sh\n", encoding="utf-8")
            (root / "python" / "envctl_engine").mkdir(parents=True)
            _write_metadata(
                root,
                {
                    "schema_version": 1,
                    "serena_project_name": "repo-feature-a-1",
                    "files": {".serena/project.yml": True, ".cgcignore": False},
                    "cgc_index_mode": "disabled",
                    "cgc_index_requested": False,
                    "cgc_index_skipped_reason": "disabled",
                },
            )

            section = CodeIntelligencePromptBuilder(_worktree(root)).prompt_section()

        self.assertIn("envctl source checkout", section)
        self.assertIn('PATH="$PWD/.venv/bin:$PATH" envctl', section)
        self.assertIn("ENVCTL_USE_REPO_WRAPPER=1 ./bin/envctl", section)

    def test_builder_adds_envctl_source_checkout_hint_without_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            (root / "bin").mkdir(parents=True)
            (root / "bin" / "envctl").write_text("#!/bin/sh\n", encoding="utf-8")
            (root / "python" / "envctl_engine").mkdir(parents=True)

            section = CodeIntelligencePromptBuilder(_worktree(root)).prompt_section()

        self.assertIn("envctl source checkout", section)
        self.assertNotIn("Serena project", section)
        self.assertNotIn("CodeGraph index", section)

    def test_builder_renders_codegraph_when_worktree_index_succeeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            (root / ".codegraph").mkdir(parents=True)
            (root / ".codegraph" / "codegraph.db").write_text("index\n", encoding="utf-8")
            _write_metadata(
                root,
                {
                    "schema_version": 1,
                    "files": {
                        ".serena/project.yml": False,
                        ".codegraph/codegraph.db": True,
                    },
                    "codegraph_index_mode": "auto",
                    "codegraph_index_requested": True,
                    "codegraph_index_succeeded": True,
                },
            )

            section = CodeIntelligencePromptBuilder(_worktree(root)).prompt_section()

        self.assertIn("## Worktree code intelligence", section)
        self.assertIn("CodeGraph index `.codegraph/` is available", section)
        self.assertIn("broad repo structure, call paths, flows, and blast-radius questions", section)
        self.assertIn('codegraph explore "<question>"', section)
        self.assertNotIn("Serena project", section)

    def test_builder_ignores_codegraph_success_metadata_when_database_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            _write_metadata(
                root,
                {
                    "schema_version": 1,
                    "files": {".serena/project.yml": False, ".codegraph/codegraph.db": True},
                    "codegraph_index_mode": "enabled",
                    "codegraph_index_requested": True,
                    "codegraph_index_succeeded": True,
                },
            )

            section = CodeIntelligencePromptBuilder(_worktree(root)).prompt_section()

        self.assertNotIn("CodeGraph index", section)

    def test_append_returns_original_prompt_when_metadata_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()

            result = _append_code_intelligence_context_for_preset(
                preset="implement_task",
                prompt_text="Implement",
                worktree=_worktree(root),
            )

        self.assertEqual(result, "Implement")

    def test_append_ignores_unavailable_codegraph_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            _write_metadata(
                root,
                {
                    "schema_version": 1,
                    "files": {".serena/project.yml": False, ".codegraph/codegraph.db": False},
                    "codegraph_index_mode": "enabled",
                    "codegraph_index_requested": True,
                    "codegraph_available": False,
                    "codegraph_index_skipped_reason": "codegraph_not_available",
                },
            )

            result = _append_code_intelligence_context_for_preset(
                preset="implement_task",
                prompt_text="Implement",
                worktree=_worktree(root),
            )

        self.assertEqual(result, "Implement")


if __name__ == "__main__":
    unittest.main()
