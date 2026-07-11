from __future__ import annotations

import os
from pathlib import Path
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
    service_start_command_resolved,
    split_command,
)


class EngineRuntimeCommandsTests(unittest.TestCase):
    def test_docker_image_command_skips_host_command_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = SimpleNamespace(
                env={
                    "DOCKER_MODE": "true",
                    "ENVCTL_FRONTEND_DOCKER_IMAGE": "example/frontend:dev",
                },
                config=SimpleNamespace(
                    base_dir=root,
                    raw={"FRONTEND_DIR": "frontend"},
                ),
                _command_exists=lambda _executable: self.fail("host command lookup must be skipped"),
            )

            command, source = service_start_command_resolved(
                runtime,
                service_name="frontend",
                project_root=root,
                port=8010,
            )

        self.assertEqual(command, [])
        self.assertEqual(source, "docker_image")

    def test_explicit_docker_command_skips_host_command_resolution(self) -> None:
        runtime = SimpleNamespace(
            env={
                "DOCKER_MODE": "true",
                "ENVCTL_BACKEND_DOCKER_COMMAND": "uvicorn app:api --port 8000",
            },
            config=SimpleNamespace(base_dir=Path("/repo"), raw={}),
            _command_exists=lambda _executable: self.fail("host command lookup must be skipped"),
        )

        command, source = service_start_command_resolved(runtime, service_name="backend", port=8000)

        self.assertEqual(command, [])
        self.assertEqual(source, "docker_command")

    def test_docker_service_command_still_requires_executable_on_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "frontend").mkdir()
            runtime = SimpleNamespace(
                env={
                    "DOCKER_MODE": "true",
                    "ENVCTL_FRONTEND_DOCKER_COMMAND_MODE": "service",
                    "ENVCTL_FRONTEND_START_CMD": "missing-command --port {port}",
                },
                config=SimpleNamespace(
                    base_dir=root,
                    raw={"FRONTEND_DIR": "frontend"},
                ),
                _command_exists=lambda _executable: False,
            )

            with self.assertRaises(RuntimeError):
                service_start_command_resolved(
                    runtime,
                    service_name="frontend",
                    project_root=root,
                    port=8010,
                )

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
            runtime = SimpleNamespace(_command_exists=lambda executable: False)

            parsed = split_command(runtime, "scripts/start-service.sh {port}", port=8123, cwd=root)

        self.assertEqual(parsed, ["scripts/start-service.sh", "8123"])

    def test_default_python_executable_falls_back_to_python3(self) -> None:
        runtime = SimpleNamespace(env={}, _command_exists=lambda executable: False)

        with tempfile.TemporaryDirectory():
            self.assertEqual(default_python_executable(runtime), "python3")


if __name__ == "__main__":
    unittest.main()
