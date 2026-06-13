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
    def test_builder_renders_serena_only_when_cgc_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
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

        self.assertIn("## Worktree code intelligence", section)
        self.assertIn("Serena project `repo-feature-a-1`", section)
        self.assertIn("symbol definitions, references, call paths, and semantic edits", section)
        self.assertNotIn("CodeGraphContext", section)
        self.assertNotIn("legacy `codegraph`", section)

    def test_builder_renders_cgc_when_source_context_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            _write_metadata(
                root,
                {
                    "schema_version": 1,
                    "files": {".serena/project.yml": False, ".cgcignore": True},
                    "cgc_context": "Repo-feature-a-1",
                    "cgc_active_context": "Repo",
                    "cgc_index_mode": "auto",
                    "cgc_index_requested": False,
                    "cgc_context_managed": False,
                    "cgc_index_skipped_reason": "source_context_reused",
                },
            )

            section = CodeIntelligencePromptBuilder(_worktree(root)).prompt_section()

        self.assertIn("## Worktree code intelligence", section)
        self.assertIn("CodeGraphContext (`cgc`) context `Repo`", section)
        self.assertIn("repo-wide ownership, coupling, impact, hotspot, and dead-code questions", section)
        self.assertIn("Do not use the legacy `codegraph` CLI or `.codegraph/` indexes", section)
        self.assertNotIn("Serena project", section)

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

    def test_append_ignores_unavailable_cgc_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            root.mkdir()
            _write_metadata(
                root,
                {
                    "schema_version": 1,
                    "files": {".serena/project.yml": False, ".cgcignore": True},
                    "cgc_context": "Repo-feature-a-1",
                    "cgc_active_context": "Repo-feature-a-1",
                    "cgc_index_mode": "enabled",
                    "cgc_index_requested": True,
                    "cgc_available": False,
                    "cgc_index_skipped_reason": "cgc_not_available",
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
