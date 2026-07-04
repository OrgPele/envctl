from __future__ import annotations

import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from unittest.mock import patch

from envctl_engine.actions.test_plan_action import build_test_plan, run_test_plan_action
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
            "uv run --extra dev pytest -q tests/python/runtime/test_prompt_install_support_templates.py",
            [item["command"] for item in result["commands"]],
        )

    def test_documentation_and_plan_changes_recommend_shared_doc_contracts_without_full_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            result = build_test_plan(
                repo_root=repo,
                project_root=repo,
                project_name="Main",
                changed_files=("docs/developer/testing-and-validation.md", "AGENTS.md", "todo/plans/features/task.md"),
            )

        commands = [item["command"] for item in result["commands"]]

        self.assertEqual(
            commands,
            [
                "uv run --extra dev pytest -q "
                "tests/python/shared/test_validation_workflow_contract.py "
                "tests/python/shared/test_serena_config.py"
            ],
        )
        self.assertEqual(result["commands"][0]["reason"], "documentation or agent tooling contract change")
        self.assertEqual(result["full_gate"]["recommended"], False)

    def test_prompt_and_documentation_changes_combine_focused_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            result = build_test_plan(
                repo_root=repo,
                project_root=repo,
                project_name="Main",
                changed_files=(
                    "python/envctl_engine/runtime/prompt_templates/implement_task.md",
                    "docs/developer/testing-and-validation.md",
                ),
            )

        commands = [item["command"] for item in result["commands"]]

        self.assertEqual(
            commands,
            [
                "uv run --extra dev pytest -q tests/python/runtime",
                "uv run --extra dev pytest -q tests/python/runtime/test_prompt_install_support_templates.py",
                "uv run --extra dev pytest -q "
                "tests/python/shared/test_validation_workflow_contract.py "
                "tests/python/shared/test_serena_config.py",
            ],
        )
        self.assertEqual(result["full_gate"]["recommended"], False)

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
                    return subprocess.CompletedProcess(
                        args=args, returncode=0, stdout="python/envctl_engine/config/__init__.py\n"
                    )
                if args[:4] == ["git", "diff", "--cached", "--name-only"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="MAIN_TASK.md\n")
                if args[:3] == ["git", "ls-files", "--others"]:
                    return subprocess.CompletedProcess(
                        args=args, returncode=0, stdout=".envctl-state/run.json\nnew_tool.py\n"
                    )
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with patch("envctl_engine.actions.test_plan_action.subprocess.run", side_effect=fake_run):
                result = build_test_plan(repo_root=repo, project_root=repo, project_name="Main")

        self.assertEqual(result["changed_files"], ["new_tool.py", "python/envctl_engine/config/__init__.py"])
        self.assertTrue(is_envctl_local_artifact_path(".envctl-commit-message.md"))
        self.assertTrue(is_envctl_local_artifact_path(".codegraph/codegraph.db"))
        self.assertTrue(is_envctl_local_artifact_path(".serena/project.local.yml"))
        self.assertFalse(is_envctl_local_artifact_path(".serena/project.yml"))
        self.assertFalse(is_envctl_local_artifact_path("docs/reference/.envctl.example"))

    def test_default_mode_executes_focused_commands_until_first_failure(self) -> None:
        class Context:
            repo_root = Path("/repo")
            project_root = Path("/repo")
            project_name = "Main"

        plan = {
            "contract_version": "envctl.test_plan.v1",
            "project": "Main",
            "repo_root": "/repo",
            "project_root": "/repo",
            "changed_files": ["python/envctl_engine/actions/test_plan_action.py"],
            "commands": [
                {"command": "uv run --extra dev pytest -q tests/python/actions"},
                {"command": "uv run --extra dev ruff check python/envctl_engine/actions/test_plan_action.py"},
            ],
            "full_gate": {"recommended": False, "command": "uv run --extra dev pytest -q tests/python"},
        }
        calls: list[list[str]] = []

        def fake_run(args: list[str], **kwargs):  # noqa: ANN001
            calls.append(args)
            self.assertEqual(kwargs["cwd"], "/repo")
            self.assertEqual(kwargs["stdout"], subprocess.PIPE)
            self.assertEqual(kwargs["stderr"], subprocess.PIPE)
            self.assertIs(kwargs["text"], True)
            return subprocess.CompletedProcess(
                args=args, returncode=1 if len(calls) == 1 else 0, stdout="failure stdout\n", stderr="failure stderr\n"
            )

        with (
            patch("envctl_engine.actions.test_plan_action.build_test_plan", return_value=plan),
            patch("envctl_engine.actions.test_plan_action.subprocess.run", side_effect=fake_run),
            redirect_stdout(StringIO()) as stdout,
        ):
            code = run_test_plan_action(Context(), json_output=True)

        self.assertEqual(code, 1)
        self.assertEqual(calls, [["uv", "run", "--extra", "dev", "pytest", "-q", "tests/python/actions"]])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["run"]["status"], "failed")
        result = payload["run"]["results"][0]
        self.assertEqual(result["returncode"], 1)
        self.assertEqual(result["stdout"], "failure stdout\n")
        self.assertEqual(result["stderr"], "failure stderr\n")
        self.assertEqual(
            payload["run"]["skipped_commands"],
            ["uv run --extra dev ruff check python/envctl_engine/actions/test_plan_action.py"],
        )

    def test_default_mode_hides_success_output_in_non_json(self) -> None:
        class Context:
            repo_root = Path("/repo")
            project_root = Path("/repo")
            project_name = "Main"

        plan = {
            "contract_version": "envctl.test_plan.v1",
            "project": "Main",
            "repo_root": "/repo",
            "project_root": "/repo",
            "changed_files": ["python/envctl_engine/actions/test_plan_action.py"],
            "commands": [{"command": "uv run --extra dev pytest -q tests/python/actions"}],
            "full_gate": {"recommended": False, "command": "uv run --extra dev pytest -q tests/python"},
        }

        def fake_run(args: list[str], **kwargs):  # noqa: ANN001
            self.assertEqual(kwargs["stdout"], subprocess.PIPE)
            self.assertEqual(kwargs["stderr"], subprocess.PIPE)
            self.assertIs(kwargs["text"], True)
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="noisy stdout\n", stderr="noisy stderr\n"
            )

        with (
            patch("envctl_engine.actions.test_plan_action.build_test_plan", return_value=plan),
            patch("envctl_engine.actions.test_plan_action.subprocess.run", side_effect=fake_run),
            redirect_stdout(StringIO()) as stdout,
        ):
            code = run_test_plan_action(Context())

        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue().splitlines(), ["passed: uv run --extra dev pytest -q tests/python/actions"])

    def test_pytest_commands_use_free_core_worker_count_when_xdist_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            python = repo / ".venv" / "bin" / "python"
            (repo / ".venv" / "lib" / "python3.12" / "site-packages" / "xdist").mkdir(parents=True)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/usr/bin/env python\n", encoding="utf-8")

            class Context:
                repo_root = repo
                project_root = repo
                project_name = "Main"
                env: dict[str, str] = {}
                config_raw: dict[str, str] = {}
                route_flags: dict[str, object] = {}

            plan = {
                "contract_version": "envctl.test_plan.v1",
                "project": "Main",
                "repo_root": str(repo),
                "project_root": str(repo),
                "changed_files": ["python/envctl_engine/actions/test_plan_action.py"],
                "commands": [{"command": "uv run --extra dev pytest -q tests/python/actions"}],
                "full_gate": {"recommended": False, "command": "uv run --extra dev pytest -q tests/python"},
            }
            calls: list[list[str]] = []

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                calls.append(args)
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

            with (
                patch("envctl_engine.actions.test_plan_action.build_test_plan", return_value=plan),
                patch("envctl_engine.actions.action_pytest_parallel_support.os.cpu_count", return_value=8),
                patch("envctl_engine.actions.action_pytest_parallel_support.os.getloadavg", return_value=(2.1, 1.0, 1.0)),
                patch("envctl_engine.actions.test_plan_action.subprocess.run", side_effect=fake_run),
                redirect_stdout(StringIO()),
            ):
                code = run_test_plan_action(Context())

        self.assertEqual(code, 0)
        self.assertEqual(
            calls,
            [[str(python.resolve()), "-m", "pytest", "-n", "5", "-q", "tests/python/actions"]],
        )

    def test_pytest_parallel_worker_count_can_be_capped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            python = repo / ".venv" / "bin" / "python"
            (repo / ".venv" / "lib" / "python3.12" / "site-packages" / "xdist").mkdir(parents=True)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/usr/bin/env python\n", encoding="utf-8")

            class Context:
                repo_root = repo
                project_root = repo
                project_name = "Main"
                env = {"ENVCTL_TEST_FOCUSED_PYTEST_WORKERS": "3"}
                config_raw: dict[str, str] = {}
                route_flags: dict[str, object] = {}

            plan = {
                "contract_version": "envctl.test_plan.v1",
                "project": "Main",
                "repo_root": str(repo),
                "project_root": str(repo),
                "changed_files": ["python/envctl_engine/actions/test_plan_action.py"],
                "commands": [{"command": "uv run --extra dev pytest -q tests/python/actions"}],
                "full_gate": {"recommended": False, "command": "uv run --extra dev pytest -q tests/python"},
            }
            calls: list[list[str]] = []

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                calls.append(args)
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

            with (
                patch("envctl_engine.actions.test_plan_action.build_test_plan", return_value=plan),
                patch("envctl_engine.actions.action_pytest_parallel_support.os.cpu_count", return_value=8),
                patch("envctl_engine.actions.test_plan_action.subprocess.run", side_effect=fake_run),
                redirect_stdout(StringIO()),
            ):
                code = run_test_plan_action(Context())

        self.assertEqual(code, 0)
        self.assertEqual(
            calls,
            [[str(python.resolve()), "-m", "pytest", "-n", "3", "-q", "tests/python/actions"]],
        )

    def test_pytest_parallel_can_be_disabled_for_focused_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            python = repo / ".venv" / "bin" / "python"
            (repo / ".venv" / "lib" / "python3.12" / "site-packages" / "xdist").mkdir(parents=True)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/usr/bin/env python\n", encoding="utf-8")

            class Context:
                repo_root = repo
                project_root = repo
                project_name = "Main"
                env = {"ENVCTL_TEST_FOCUSED_PYTEST_PARALLEL": "false"}
                config_raw: dict[str, str] = {}
                route_flags: dict[str, object] = {}

            plan = {
                "contract_version": "envctl.test_plan.v1",
                "project": "Main",
                "repo_root": str(repo),
                "project_root": str(repo),
                "changed_files": ["python/envctl_engine/actions/test_plan_action.py"],
                "commands": [{"command": "uv run --extra dev pytest -q tests/python/actions"}],
                "full_gate": {"recommended": False, "command": "uv run --extra dev pytest -q tests/python"},
            }
            calls: list[list[str]] = []

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                calls.append(args)
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

            with (
                patch("envctl_engine.actions.test_plan_action.build_test_plan", return_value=plan),
                patch("envctl_engine.actions.test_plan_action.subprocess.run", side_effect=fake_run),
                redirect_stdout(StringIO()),
            ):
                code = run_test_plan_action(Context())

        self.assertEqual(code, 0)
        self.assertEqual(calls, [[str(python.resolve()), "-m", "pytest", "-q", "tests/python/actions"]])

    def test_focused_pytest_parallel_respects_plugin_autoload_disable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            python = repo / ".venv" / "bin" / "python"
            (repo / ".venv" / "lib" / "python3.12" / "site-packages" / "xdist").mkdir(parents=True)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/usr/bin/env python\n", encoding="utf-8")

            class Context:
                repo_root = repo
                project_root = repo
                project_name = "Main"
                env = {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
                config_raw: dict[str, str] = {}
                route_flags: dict[str, object] = {}

            plan = {
                "contract_version": "envctl.test_plan.v1",
                "project": "Main",
                "repo_root": str(repo),
                "project_root": str(repo),
                "changed_files": ["python/envctl_engine/actions/test_plan_action.py"],
                "commands": [{"command": "uv run --extra dev pytest -q tests/python/actions"}],
                "full_gate": {"recommended": False, "command": "uv run --extra dev pytest -q tests/python"},
            }
            calls: list[list[str]] = []

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                calls.append(args)
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

            with (
                patch("envctl_engine.actions.test_plan_action.build_test_plan", return_value=plan),
                patch("envctl_engine.actions.action_pytest_parallel_support.os.cpu_count", return_value=8),
                patch("envctl_engine.actions.test_plan_action.subprocess.run", side_effect=fake_run),
                redirect_stdout(StringIO()),
            ):
                code = run_test_plan_action(Context())

        self.assertEqual(code, 0)
        self.assertEqual(calls, [[str(python.resolve()), "-m", "pytest", "-q", "tests/python/actions"]])

    def test_default_mode_prints_failure_output_in_non_json(self) -> None:
        class Context:
            repo_root = Path("/repo")
            project_root = Path("/repo")
            project_name = "Main"

        plan = {
            "contract_version": "envctl.test_plan.v1",
            "project": "Main",
            "repo_root": "/repo",
            "project_root": "/repo",
            "changed_files": ["python/envctl_engine/actions/test_plan_action.py"],
            "commands": [{"command": "uv run --extra dev pytest -q tests/python/actions"}],
            "full_gate": {"recommended": False, "command": "uv run --extra dev pytest -q tests/python"},
        }

        def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
            return subprocess.CompletedProcess(
                args=args, returncode=2, stdout="failure stdout\n", stderr="failure stderr\n"
            )

        with (
            patch("envctl_engine.actions.test_plan_action.build_test_plan", return_value=plan),
            patch("envctl_engine.actions.test_plan_action.subprocess.run", side_effect=fake_run),
            redirect_stdout(StringIO()) as stdout,
        ):
            code = run_test_plan_action(Context())

        self.assertEqual(code, 2)
        self.assertEqual(
            stdout.getvalue().splitlines(),
            [
                "failed: uv run --extra dev pytest -q tests/python/actions",
                "stdout:",
                "failure stdout",
                "stderr:",
                "failure stderr",
            ],
        )

    def test_default_mode_uses_repo_venv_for_uv_dev_pytest_command_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            python_path = repo.resolve() / ".venv" / "bin" / "python"
            python_path.parent.mkdir(parents=True)
            python_path.write_text("#!/bin/sh\n", encoding="utf-8")
            python_path.chmod(0o755)

            class Context:
                repo_root = repo
                project_root = repo
                project_name = "Main"

            plan = {
                "contract_version": "envctl.test_plan.v1",
                "project": "Main",
                "repo_root": str(repo),
                "project_root": str(repo),
                "changed_files": [],
                "commands": [{"command": "uv run --extra dev pytest -q tests/python"}],
                "full_gate": {"recommended": False, "command": "uv run --extra dev pytest -q tests/python"},
            }
            calls: list[list[str]] = []

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                calls.append(args)
                return subprocess.CompletedProcess(args=args, returncode=0)

            with (
                patch("envctl_engine.actions.test_plan_action.build_test_plan", return_value=plan),
                patch("envctl_engine.actions.test_plan_action.subprocess.run", side_effect=fake_run),
                redirect_stdout(StringIO()) as stdout,
            ):
                code = run_test_plan_action(Context(), json_output=True)

        self.assertEqual(code, 0)
        self.assertEqual(calls, [[str(python_path), "-m", "pytest", "-q", "tests/python"]])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["run"]["results"][0]["command"], "uv run --extra dev pytest -q tests/python")
        self.assertEqual(
            payload["run"]["results"][0]["executed_command"],
            f"{python_path} -m pytest -q tests/python",
        )

    def test_default_mode_reports_signal_termination_details(self) -> None:
        class Context:
            repo_root = Path("/repo")
            project_root = Path("/repo")
            project_name = "Main"

        plan = {
            "contract_version": "envctl.test_plan.v1",
            "project": "Main",
            "repo_root": "/repo",
            "project_root": "/repo",
            "changed_files": [],
            "commands": [{"command": "uv run --extra dev pytest -q tests/python"}],
            "full_gate": {"recommended": False, "command": "uv run --extra dev pytest -q tests/python"},
        }

        with (
            patch("envctl_engine.actions.test_plan_action.build_test_plan", return_value=plan),
            patch(
                "envctl_engine.actions.test_plan_action.subprocess.run",
                return_value=subprocess.CompletedProcess(args=["uv"], returncode=-9),
            ),
            redirect_stdout(StringIO()) as stdout,
        ):
            code = run_test_plan_action(Context(), json_output=True)

        self.assertEqual(code, -9)
        result = json.loads(stdout.getvalue())["run"]["results"][0]
        self.assertEqual(result["status"], "terminated_by_signal")
        self.assertEqual(result["signal"], 9)
        self.assertEqual(result["signal_name"], "SIGKILL")

    def test_default_mode_reports_success_after_all_focused_commands_pass(self) -> None:
        class Context:
            repo_root = Path("/repo")
            project_root = Path("/repo")
            project_name = "Main"

        plan = {
            "contract_version": "envctl.test_plan.v1",
            "project": "Main",
            "repo_root": "/repo",
            "project_root": "/repo",
            "changed_files": ["python/envctl_engine/actions/test_plan_action.py"],
            "commands": [
                {"command": "uv run --extra dev pytest -q tests/python/actions"},
                {"command": "uv run --extra dev ruff check python/envctl_engine/actions/test_plan_action.py"},
            ],
            "full_gate": {"recommended": False, "command": "uv run --extra dev pytest -q tests/python"},
        }
        calls: list[list[str]] = []

        def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
            calls.append(args)
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="noisy stdout\n", stderr="noisy stderr\n"
            )

        with (
            patch("envctl_engine.actions.test_plan_action.build_test_plan", return_value=plan),
            patch("envctl_engine.actions.test_plan_action.subprocess.run", side_effect=fake_run),
            redirect_stdout(StringIO()) as stdout,
        ):
            code = run_test_plan_action(Context(), json_output=True)

        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["run"]["status"], "passed")
        self.assertEqual([item["status"] for item in payload["run"]["results"]], ["passed", "passed"])
        self.assertTrue(all("stdout" not in item and "stderr" not in item for item in payload["run"]["results"]))
        self.assertEqual(payload["run"]["skipped_commands"], [])

    def test_dry_run_mode_prints_focused_commands_without_running_them(self) -> None:
        class Context:
            repo_root = Path("/repo")
            project_root = Path("/repo")
            project_name = "Main"

        plan = {
            "contract_version": "envctl.test_plan.v1",
            "project": "Main",
            "repo_root": "/repo",
            "project_root": "/repo",
            "changed_files": ["python/envctl_engine/actions/test_plan_action.py"],
            "commands": [
                {"command": "uv run --extra dev pytest -q tests/python/actions"},
                {"command": "uv run --extra dev ruff check python/envctl_engine/actions/test_plan_action.py"},
            ],
            "full_gate": {"recommended": False, "command": "uv run --extra dev pytest -q tests/python"},
        }

        with (
            patch("envctl_engine.actions.test_plan_action.build_test_plan", return_value=plan),
            patch("envctl_engine.actions.test_plan_action.subprocess.run") as run,
            redirect_stdout(StringIO()) as stdout,
        ):
            code = run_test_plan_action(Context(), dry_run=True)

        self.assertEqual(code, 0)
        run.assert_not_called()
        self.assertEqual(
            stdout.getvalue().splitlines(),
            [
                "uv run --extra dev pytest -q tests/python/actions",
                "uv run --extra dev ruff check python/envctl_engine/actions/test_plan_action.py",
            ],
        )


if __name__ == "__main__":
    unittest.main()
