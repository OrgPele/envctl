from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace


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

    def test_default_python_executable_falls_back_to_python3(self) -> None:
        runtime = SimpleNamespace(env={}, _command_exists=lambda executable: False)

        with tempfile.TemporaryDirectory():
            self.assertEqual(default_python_executable(runtime), "python3")


if __name__ == "__main__":
    unittest.main()
