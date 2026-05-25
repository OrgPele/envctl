from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from envctl_engine.config import (
    _resolved_backend_dir_name,
    _resolved_backend_test_cmd,
    _resolved_frontend_test_path,
)
from envctl_engine.config.command_defaults import (
    resolved_action_test_cmd,
    resolved_backend_dir_name,
    resolved_backend_start_cmd,
    resolved_backend_test_cmd,
    resolved_frontend_dir_name,
    resolved_frontend_start_cmd,
    resolved_frontend_test_cmd,
    resolved_frontend_test_path,
)


class ConfigCommandDefaultsTests(unittest.TestCase):
    def test_explicit_directory_values_are_preserved_without_autodetection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)

            self.assertEqual(
                resolved_backend_dir_name(
                    base_dir=repo,
                    resolved={"BACKEND_DIR": "api"},
                    explicit_values={"BACKEND_DIR": "api"},
                ),
                "api",
            )
            self.assertEqual(
                resolved_frontend_dir_name(
                    base_dir=repo,
                    resolved={"FRONTEND_DIR": "web"},
                    explicit_values={"FRONTEND_DIR": "web"},
                ),
                "web",
            )

    def test_directory_values_fall_back_to_repo_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / "src").mkdir()
            (repo / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
            frontend = repo / "frontend"
            frontend.mkdir()
            (frontend / "package.json").write_text('{"scripts":{"dev":"vite"}}\n', encoding="utf-8")

            self.assertEqual(resolved_backend_dir_name(base_dir=repo, resolved={}, explicit_values={}), "src")
            self.assertEqual(resolved_frontend_dir_name(base_dir=repo, resolved={}, explicit_values={}), "frontend")
            self.assertEqual(_resolved_backend_dir_name(base_dir=repo, resolved={}, explicit_values={}), "src")

    def test_start_commands_prefer_explicit_values_and_otherwise_detect_supported_layouts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            backend = repo / "backend"
            backend.mkdir()
            (backend / "pyproject.toml").write_text("[project]\nname = 'sample-backend'\n", encoding="utf-8")
            (backend / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
            frontend = repo / "frontend"
            frontend.mkdir()
            (frontend / "package.json").write_text('{"scripts":{"dev":"vite --host 0.0.0.0"}}\n', encoding="utf-8")

            self.assertEqual(
                resolved_backend_start_cmd(base_dir=repo, resolved={"ENVCTL_BACKEND_START_CMD": "custom backend"}),
                "custom backend",
            )
            backend_start_cmd = resolved_backend_start_cmd(base_dir=repo, resolved={})
            self.assertIn("python -m uvicorn", backend_start_cmd)
            self.assertIn("main:app", backend_start_cmd)
            self.assertEqual(
                resolved_frontend_start_cmd(base_dir=repo, resolved={"ENVCTL_FRONTEND_START_CMD": "custom frontend"}),
                "custom frontend",
            )
            self.assertIn("npm", resolved_frontend_start_cmd(base_dir=repo, resolved={}))

    def test_backend_start_command_returns_empty_string_for_unsupported_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            backend = repo / "backend"
            backend.mkdir()
            (backend / "package.json").write_text('{"scripts":{"dev":"node server.js"}}\n', encoding="utf-8")

            self.assertEqual(resolved_backend_start_cmd(base_dir=repo, resolved={}), "")

    def test_backend_and_frontend_test_commands_use_shared_action_command_before_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            tests_dir = repo / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

            self.assertEqual(
                resolved_backend_test_cmd(base_dir=repo, resolved={"ENVCTL_ACTION_TEST_CMD": "uv run pytest"}),
                "uv run pytest",
            )
            self.assertEqual(
                resolved_frontend_test_cmd(base_dir=repo, resolved={"ENVCTL_ACTION_TEST_CMD": "uv run pytest"}),
                "uv run pytest",
            )
            self.assertEqual(
                _resolved_backend_test_cmd(base_dir=repo, resolved={"ENVCTL_ACTION_TEST_CMD": "uv run pytest"}),
                "uv run pytest",
            )

    def test_test_commands_prefer_specific_explicit_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)

            self.assertEqual(
                resolved_action_test_cmd(base_dir=repo, resolved={"ENVCTL_ACTION_TEST_CMD": "make test"}),
                "make test",
            )
            self.assertEqual(
                resolved_backend_test_cmd(base_dir=repo, resolved={"ENVCTL_BACKEND_TEST_CMD": "pytest api"}),
                "pytest api",
            )
            self.assertEqual(
                resolved_frontend_test_cmd(base_dir=repo, resolved={"ENVCTL_FRONTEND_TEST_CMD": "npm test"}),
                "npm test",
            )

    def test_frontend_test_path_canonicalizes_saved_relative_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            frontend = repo / "frontend"
            src = frontend / "src"
            src.mkdir(parents=True)
            (frontend / "package.json").write_text('{"scripts":{"test":"vitest run"}}\n', encoding="utf-8")
            (src / "app.test.ts").write_text("it('works', () => {})\n", encoding="utf-8")

            resolved = {"FRONTEND_DIR": "frontend", "ENVCTL_FRONTEND_TEST_PATH": "src"}

            self.assertEqual(resolved_frontend_test_path(base_dir=repo, resolved=resolved), "frontend/src")
            self.assertEqual(_resolved_frontend_test_path(base_dir=repo, resolved=resolved), "frontend/src")


if __name__ == "__main__":
    unittest.main()
