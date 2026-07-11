from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.engine_runtime_commands import (  # noqa: E402
    command_env,
    command_override_value,
    default_python_executable,
    split_command,
)


class EngineRuntimeCommandsTests(unittest.TestCase):
    def test_command_override_value_prefers_runtime_env(self) -> None:
        runtime = SimpleNamespace(
            env={"DB_HOST": "env-db"},
            config=SimpleNamespace(raw={"DB_HOST": "config-db", "DB_USER": "alice"}),
        )

        self.assertEqual(command_override_value(runtime, "DB_HOST"), "env-db")
        self.assertEqual(command_override_value(runtime, "DB_USER"), "alice")
        self.assertIsNone(command_override_value(runtime, "MISSING"))

    def test_split_command_applies_replacements_and_port(self) -> None:
        runtime = SimpleNamespace(_command_exists=lambda executable: executable == "python3")

        parsed = split_command(
            runtime,
            "python3 app.py --name {project} --port {port}",
            port=8123,
            replacements={"project": "feature-a"},
        )

        self.assertEqual(parsed, ["python3", "app.py", "--name", "feature-a", "--port", "8123"])

    def test_command_env_sets_port_and_overrides(self) -> None:
        runtime = SimpleNamespace(env={"A": "1"})

        env = command_env(runtime, port=9000, extra={"B": "2"})

        self.assertEqual(env["PORT"], "9000")
        self.assertEqual(env["A"], "1")
        self.assertEqual(env["B"], "2")
        self.assertEqual(env["ENVCTL_PYTHON_EXECUTABLE"], sys.executable)

    def test_command_env_keeps_running_interpreter_authoritative(self) -> None:
        runtime = SimpleNamespace(env={"ENVCTL_PYTHON_EXECUTABLE": "/stale/runtime/python"})

        with patch(
            "envctl_engine.runtime.engine_runtime_commands.sys.executable",
            "/opt/envctl/bin/python",
        ):
            env = command_env(
                runtime,
                port=9000,
                extra={"ENVCTL_PYTHON_EXECUTABLE": "/spoofed/project/python"},
            )

        self.assertEqual(env["ENVCTL_PYTHON_EXECUTABLE"], "/opt/envctl/bin/python")

    def test_command_env_strips_github_actions_cleanup_variables(self) -> None:
        runtime = SimpleNamespace(env={"A": "1"})
        actions_env = {
            "RUNNER_TRACKING_ID": "github-cleanup-token",
            "ACTIONS_RUNTIME_TOKEN": "secret",
            "GITHUB_TOKEN": "secret",
            "GH_TOKEN": "secret",
            "KEEP_ME": "value",
        }

        with patch.dict(os.environ, actions_env, clear=True):
            env = command_env(runtime, port=9000)

        self.assertNotIn("RUNNER_TRACKING_ID", env)
        self.assertNotIn("ACTIONS_RUNTIME_TOKEN", env)
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("GH_TOKEN", env)
        self.assertEqual(env["KEEP_ME"], "value")
        self.assertEqual(env["A"], "1")
        self.assertEqual(env["PORT"], "9000")

    def test_command_env_strips_github_actions_cleanup_variables_from_runtime_env(self) -> None:
        runtime = SimpleNamespace(
            env={
                "A": "1",
                "RUNNER_TRACKING_ID": "runtime-cleanup-token",
                "ACTIONS_RUNTIME_TOKEN": "runtime-secret",
            }
        )

        env = command_env(
            runtime,
            port=9000,
            extra={"B": "2", "GITHUB_TOKEN": "extra-secret"},
        )

        self.assertNotIn("RUNNER_TRACKING_ID", env)
        self.assertNotIn("ACTIONS_RUNTIME_TOKEN", env)
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertEqual(env["A"], "1")
        self.assertEqual(env["B"], "2")
        self.assertEqual(env["PORT"], "9000")

    def test_default_python_executable_prefers_runtime_override(self) -> None:
        runtime = SimpleNamespace(
            env={"PYTHON_BIN": "/custom/python"},
            _command_exists=lambda executable: executable == "/custom/python",
        )

        self.assertEqual(default_python_executable(runtime), "/custom/python")

    def test_split_command_rejects_missing_executable(self) -> None:
        runtime = SimpleNamespace(_command_exists=lambda executable: False)

        with self.assertRaises(RuntimeError):
            split_command(runtime, "python3 app.py")

    def test_split_command_accepts_relative_executable_from_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            script = root / "scripts" / "start-service.sh"
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text("#!/usr/bin/env sh\n", encoding="utf-8")
            script.chmod(0o755)
            runtime = SimpleNamespace(_command_exists=lambda executable: False)

            parsed = split_command(runtime, "scripts/start-service.sh {port}", port=8123, cwd=root)

        self.assertEqual(parsed, ["scripts/start-service.sh", "8123"])

    def test_split_command_rejects_non_executable_file_and_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            file_path = root / "start-service.sh"
            file_path.write_text("#!/usr/bin/env sh\n", encoding="utf-8")
            directory_path = root / "service-dir"
            directory_path.mkdir()
            runtime = SimpleNamespace(_command_exists=lambda _executable: True)

            for command in (str(file_path), str(directory_path)):
                with (
                    self.subTest(command=command),
                    self.assertRaisesRegex(
                        RuntimeError,
                        "Resolved command executable not found",
                    ),
                ):
                    split_command(runtime, command, cwd=root)

    def test_default_python_executable_falls_back_to_python3(self) -> None:
        runtime = SimpleNamespace(env={}, _command_exists=lambda executable: False)

        with tempfile.TemporaryDirectory():
            self.assertEqual(default_python_executable(runtime), "python3")


if __name__ == "__main__":
    unittest.main()
