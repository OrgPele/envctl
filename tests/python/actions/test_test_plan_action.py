from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from envctl_engine.actions.test_plan_action import build_test_plan
from envctl_engine.config.local_artifacts import is_envctl_local_artifact_path


class TestPlanActionTests(unittest.TestCase):
    def test_changed_planning_files_recommend_planning_tests_and_ruff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            result = build_test_plan(
                repo_root=repo,
                project_root=repo,
                project_name="Main",
                changed_files=("python/envctl_engine/planning/worktree_domain.py",),
            )

        commands = [item["command"] for item in result["commands"]]

        self.assertIn("uv run --extra dev pytest -q tests/python/planning", commands)
        self.assertIn("uv run --extra dev ruff check python/envctl_engine/planning/worktree_domain.py", commands)
        self.assertEqual(result["full_gate"]["recommended"], False)

    def test_prompt_templates_recommend_prompt_install_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            result = build_test_plan(
                repo_root=repo,
                project_root=repo,
                project_name="Main",
                changed_files=("python/envctl_engine/runtime/prompt_templates/implement_task.md",),
            )

        self.assertIn(
            "uv run --extra dev pytest -q tests/python/runtime/test_prompt_install_support.py",
            [item["command"] for item in result["commands"]],
        )

    def test_mixed_runtime_and_script_changes_recommend_full_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            result = build_test_plan(
                repo_root=repo,
                project_root=repo,
                project_name="Main",
                changed_files=("python/envctl_engine/runtime/command_router.py", "scripts/release_shipability_gate.py"),
            )

        self.assertEqual(result["full_gate"]["recommended"], True)
        self.assertIn("contract-affecting", result["full_gate"]["reason"])

    def test_changed_files_are_collected_from_git_and_skip_envctl_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                if args[:3] == ["git", "diff", "--name-only"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="python/envctl_engine/config/__init__.py\n")
                if args[:4] == ["git", "diff", "--cached", "--name-only"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="MAIN_TASK.md\n")
                if args[:3] == ["git", "ls-files", "--others"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout=".envctl-state/run.json\nnew_tool.py\n")
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with patch("envctl_engine.actions.test_plan_action.subprocess.run", side_effect=fake_run):
                result = build_test_plan(repo_root=repo, project_root=repo, project_name="Main")

        self.assertEqual(result["changed_files"], ["new_tool.py", "python/envctl_engine/config/__init__.py"])
        self.assertTrue(is_envctl_local_artifact_path(".envctl-commit-message.md"))


if __name__ == "__main__":
    unittest.main()
