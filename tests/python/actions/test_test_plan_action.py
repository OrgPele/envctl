from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import signal
from pathlib import Path
from unittest.mock import patch

from envctl_engine.actions import test_plan_action
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

    def test_shared_runtime_files_recommend_shared_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            result = build_test_plan(
                repo_root=repo,
                project_root=repo,
                project_name="Main",
                changed_files=("python/envctl_engine/shared/process_streaming_support.py",),
            )

        commands = [item["command"] for item in result["commands"]]

        self.assertIn("uv run --extra dev pytest -q tests/python/shared", commands)
        self.assertIn(
            "uv run --extra dev ruff check python/envctl_engine/shared/process_streaming_support.py",
            commands,
        )

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

    def test_documentation_changes_recommend_shared_doc_contracts_without_full_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            result = build_test_plan(
                repo_root=repo,
                project_root=repo,
                project_name="Main",
                changed_files=("docs/developer/testing-and-validation.md", "AGENTS.md"),
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
            self.assertEqual(kwargs["cwd"], Path("/repo"))
            self.assertIsInstance(kwargs["env"], dict)
            return subprocess.CompletedProcess(
                args=args, returncode=1 if len(calls) == 1 else 0, stdout="failure stdout\n", stderr="failure stderr\n"
            )

        with (
            patch("envctl_engine.actions.test_plan_action.build_test_plan", return_value=plan),
            patch("envctl_engine.actions.test_plan_action._run_test_command", side_effect=fake_run),
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
            self.assertEqual(kwargs["cwd"], Path("/repo"))
            self.assertIsInstance(kwargs["env"], dict)
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="noisy stdout\n", stderr="noisy stderr\n"
            )

        with (
            patch("envctl_engine.actions.test_plan_action.build_test_plan", return_value=plan),
            patch("envctl_engine.actions.test_plan_action._run_test_command", side_effect=fake_run),
            redirect_stdout(StringIO()) as stdout,
            redirect_stderr(StringIO()) as stderr,
        ):
            code = run_test_plan_action(Context())

        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue().splitlines(), ["passed: uv run --extra dev pytest -q tests/python/actions"])
        self.assertEqual(stderr.getvalue().splitlines(), ["running: uv run --extra dev pytest -q tests/python/actions"])

    def test_default_mode_isolates_test_subprocess_from_envctl_launcher_env(self) -> None:
        class Context:
            repo_root = Path("/repo")
            project_root = Path("/repo")
            project_name = "Main"
            env = {"RUN_REPO_ROOT": "/runtime/repo", "KEEP_RUNTIME": "no"}

        plan = {
            "contract_version": "envctl.test_plan.v1",
            "project": "Main",
            "repo_root": "/repo",
            "project_root": "/repo",
            "changed_files": [],
            "commands": [{"command": "uv run --extra dev pytest -q tests/python"}],
            "full_gate": {"recommended": False, "command": "uv run --extra dev pytest -q tests/python"},
        }
        seen_kwargs: dict[str, object] = {}

        def fake_run(args: list[str], **kwargs):  # noqa: ANN001
            seen_kwargs.update(kwargs)
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

        dirty_parent_env = {
            "KEEP_ME": "1",
            "ENVCTL_ROOT_DIR": "/repo",
            "ENVCTL_USE_REPO_WRAPPER": "1",
            "ENVCTL_WRAPPER_ORIGINAL_ARGV0": "./bin/envctl",
            "ENVCTL_WRAPPER_PYTHON_REEXEC": "1",
            "ENVCTL_EXECUTION_ROOT": "/repo/trees/feature/1",
            "ENVCTL_ACTION_COMMAND": "test-focused",
            "ENVCTL_ACTION_PROJECT": "feature-1",
            "ENVCTL_ACTION_PROJECT_ROOT": "/repo/trees/feature/1",
            "ENVCTL_ACTION_REPO_ROOT": "/repo",
            "ENVCTL_ACTION_INTERACTIVE": "1",
            "RUN_ENGINE_PATH": "python:envctl_engine.runtime.cli",
            "RUN_LAUNCHER_CONTEXT": "envctl",
            "RUN_LAUNCHER_NAME": "envctl",
            "RUN_REPO_ROOT": "/repo",
            "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
        }
        with (
            patch.dict(os.environ, dirty_parent_env, clear=True),
            patch("envctl_engine.actions.test_plan_action.build_test_plan", return_value=plan),
            patch("envctl_engine.actions.test_plan_action._run_test_command", side_effect=fake_run),
            redirect_stdout(StringIO()),
        ):
            code = run_test_plan_action(Context(), json_output=True)

        self.assertEqual(code, 0)
        child_env = seen_kwargs["env"]
        self.assertIsInstance(child_env, dict)
        assert isinstance(child_env, dict)
        self.assertEqual(child_env.get("KEEP_ME"), "1")
        self.assertNotIn("KEEP_RUNTIME", child_env)
        for key in dirty_parent_env:
            if key != "KEEP_ME":
                self.assertNotIn(key, child_env)

    def test_pytest_commands_use_free_core_worker_count_when_xdist_is_enabled(self) -> None:
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
                route_flags = {"test_parallel": True}

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
                patch("envctl_engine.actions.test_plan_action.shutil.which", return_value="/usr/bin/uv"),
                patch("envctl_engine.actions.action_pytest_parallel_support.os.cpu_count", return_value=8),
                patch("envctl_engine.actions.action_pytest_parallel_support.os.getloadavg", return_value=(2.1, 1.0, 1.0)),
                patch("envctl_engine.actions.test_plan_action._run_test_command", side_effect=fake_run),
                redirect_stdout(StringIO()),
            ):
                code = run_test_plan_action(Context())

        self.assertEqual(code, 0)
        self.assertEqual(
            calls,
            [["uv", "run", "--extra", "dev", "pytest", "-n", "5", "-q", "tests/python/actions"]],
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
                env = {
                    "ENVCTL_TEST_FOCUSED_PYTEST_PARALLEL": "true",
                    "ENVCTL_TEST_FOCUSED_PYTEST_WORKERS": "3",
                }
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
                patch("envctl_engine.actions.test_plan_action.shutil.which", return_value="/usr/bin/uv"),
                patch("envctl_engine.actions.action_pytest_parallel_support.os.cpu_count", return_value=8),
                patch("envctl_engine.actions.test_plan_action._run_test_command", side_effect=fake_run),
                redirect_stdout(StringIO()),
            ):
                code = run_test_plan_action(Context())

        self.assertEqual(code, 0)
        self.assertEqual(
            calls,
            [["uv", "run", "--extra", "dev", "pytest", "-n", "3", "-q", "tests/python/actions"]],
        )

    def test_pytest_parallel_is_disabled_by_default_for_focused_runs(self) -> None:
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
                patch("envctl_engine.actions.test_plan_action.shutil.which", return_value="/usr/bin/uv"),
                patch("envctl_engine.actions.test_plan_action._run_test_command", side_effect=fake_run),
                redirect_stdout(StringIO()),
            ):
                code = run_test_plan_action(Context())

        self.assertEqual(code, 0)
        self.assertEqual(calls, [["uv", "run", "--extra", "dev", "pytest", "-q", "tests/python/actions"]])

    def test_runtime_focused_pytest_runs_without_xdist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".venv" / "lib" / "python3.12" / "site-packages" / "xdist").mkdir(parents=True)

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
                "changed_files": ["python/envctl_engine/runtime/command_router.py"],
                "commands": [{"command": "uv run --extra dev pytest -q tests/python/runtime"}],
                "full_gate": {"recommended": False, "command": "uv run --extra dev pytest -q tests/python"},
            }
            calls: list[list[str]] = []

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                calls.append(args)
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

            with (
                patch("envctl_engine.actions.test_plan_action.build_test_plan", return_value=plan),
                patch("envctl_engine.actions.test_plan_action.shutil.which", return_value="/usr/bin/uv"),
                patch("envctl_engine.actions.action_pytest_parallel_support.os.cpu_count", return_value=8),
                patch("envctl_engine.actions.test_plan_action._run_test_command", side_effect=fake_run),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                code = run_test_plan_action(Context())

        self.assertEqual(code, 0)
        self.assertEqual(calls, [["uv", "run", "--extra", "dev", "pytest", "-q", "tests/python/runtime"]])

    def test_low_confidence_full_fallback_runs_single_thread_by_default(self) -> None:
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
                "changed_files": [],
                "commands": [
                    {
                        "command": "uv run --extra dev pytest -q tests/python",
                        "confidence": "low",
                        "reason": "no focused mapping matched changed files",
                    }
                ],
                "full_gate": {"recommended": False, "command": "uv run --extra dev pytest -q tests/python"},
            }
            calls: list[list[str]] = []

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                calls.append(args)
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

            with (
                patch("envctl_engine.actions.test_plan_action.build_test_plan", return_value=plan),
                patch("envctl_engine.actions.test_plan_action.shutil.which", return_value="/usr/bin/uv"),
                patch("envctl_engine.actions.action_pytest_parallel_support.os.cpu_count", return_value=18),
                patch("envctl_engine.actions.action_pytest_parallel_support.os.getloadavg", return_value=(0.1, 0.1, 0.1)),
                patch("envctl_engine.actions.test_plan_action._run_test_command", side_effect=fake_run),
                redirect_stdout(StringIO()),
            ):
                code = run_test_plan_action(Context())

        self.assertEqual(code, 0)
        self.assertEqual(calls, [["uv", "run", "--extra", "dev", "pytest", "-q", "tests/python"]])

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
                route_flags = {"test_parallel": True}

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
                patch("envctl_engine.actions.test_plan_action.shutil.which", return_value="/usr/bin/uv"),
                patch("envctl_engine.actions.action_pytest_parallel_support.os.cpu_count", return_value=8),
                patch("envctl_engine.actions.test_plan_action._run_test_command", side_effect=fake_run),
                redirect_stdout(StringIO()),
            ):
                code = run_test_plan_action(Context())

        self.assertEqual(code, 0)
        self.assertEqual(calls, [["uv", "run", "--extra", "dev", "pytest", "-q", "tests/python/actions"]])

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
            patch("envctl_engine.actions.test_plan_action._run_test_command", side_effect=fake_run),
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

    def test_default_mode_prefers_uv_when_available_for_uv_dev_command(self) -> None:
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
        calls: list[list[str]] = []

        def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
            calls.append(args)
            return subprocess.CompletedProcess(args=args, returncode=0)

        with (
            patch("envctl_engine.actions.test_plan_action.build_test_plan", return_value=plan),
            patch("envctl_engine.actions.test_plan_action.shutil.which", return_value="/usr/bin/uv"),
            patch("envctl_engine.actions.test_plan_action._run_test_command", side_effect=fake_run),
            redirect_stdout(StringIO()) as stdout,
        ):
            code = run_test_plan_action(Context(), json_output=True)

        self.assertEqual(code, 0)
        self.assertEqual(calls, [["uv", "run", "--extra", "dev", "pytest", "-q", "tests/python"]])
        payload = json.loads(stdout.getvalue())
        self.assertNotIn("executed_command", payload["run"]["results"][0])

    def test_default_mode_uses_repo_venv_for_uv_dev_pytest_command_when_uv_is_missing(self) -> None:
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
                patch("envctl_engine.actions.test_plan_action.shutil.which", return_value=None),
                patch("envctl_engine.actions.test_plan_action._run_test_command", side_effect=fake_run),
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
                "envctl_engine.actions.test_plan_action._run_test_command",
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

    def test_run_test_command_kills_child_process_group_on_interrupt(self) -> None:
        class FakeProcess:
            pid = 4321
            returncode = -15

            def __init__(self) -> None:
                self.stdout = StringIO("")
                self.stderr = StringIO("")
                self.wait_calls = 0

            def wait(self, timeout: float | None = None):  # noqa: ANN001, ANN202
                self.wait_calls += 1
                if self.wait_calls == 1:
                    raise KeyboardInterrupt
                if self.wait_calls == 2:
                    raise subprocess.TimeoutExpired(cmd=["pytest"], timeout=timeout)
                return self.returncode

        process = FakeProcess()
        kill_calls: list[tuple[int, int]] = []

        def fake_killpg(pid: int, sig: int) -> None:
            kill_calls.append((pid, sig))

        with (
            patch("envctl_engine.actions.test_plan_action.subprocess.Popen", return_value=process) as popen,
            patch("envctl_engine.actions.test_plan_action.os.killpg", side_effect=fake_killpg),
            self.assertRaises(KeyboardInterrupt),
        ):
            test_plan_action._run_test_command(["pytest"], cwd=Path("/repo"), env={"KEEP": "1"})

        popen.assert_called_once()
        self.assertIs(popen.call_args.kwargs["start_new_session"], True)
        self.assertEqual(kill_calls, [(4321, signal.SIGTERM), (4321, signal.SIGKILL)])

    def test_run_test_command_emits_progress_while_waiting(self) -> None:
        class FakeProcess:
            pid = 4321
            returncode = 0

            def __init__(self) -> None:
                self.stdout = StringIO("stdout\n")
                self.stderr = StringIO("stderr\n")
                self.wait_calls = 0

            def wait(self, timeout: float | None = None):  # noqa: ANN001, ANN202
                self.wait_calls += 1
                if self.wait_calls == 1:
                    raise subprocess.TimeoutExpired(cmd=["pytest", "-q"], timeout=timeout)
                return self.returncode

        process = FakeProcess()
        with (
            patch("envctl_engine.actions.test_plan_action.subprocess.Popen", return_value=process),
            patch("envctl_engine.actions.test_plan_action._TEST_COMMAND_PROGRESS_SECONDS", 0.01),
            redirect_stdout(StringIO()) as stdout,
            redirect_stderr(StringIO()) as stderr,
        ):
            completed = test_plan_action._run_test_command(["pytest", "-q"], cwd=Path("/repo"), env={"KEEP": "1"})

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "stdout\n")
        self.assertEqual(completed.stderr, "stderr\n")
        self.assertEqual(stdout.getvalue().splitlines(), ["stdout"])
        self.assertIn("stderr", stderr.getvalue().splitlines())
        self.assertIn("still running: pytest -q", stderr.getvalue().splitlines())

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
            patch("envctl_engine.actions.test_plan_action._run_test_command", side_effect=fake_run),
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
