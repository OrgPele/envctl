from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.startup.service_env_support import _read_env_file_safe
from envctl_engine.startup.service_frontend_bootstrap_support import (
    _frontend_install_commands,
    _frontend_missing_direct_dependency,
    _prepare_frontend_runtime,
)


class ServiceFrontendBootstrapSupportTests(unittest.TestCase):
    def test_missing_direct_dependency_detects_scoped_declared_package_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            frontend = Path(tmpdir)
            (frontend / "node_modules" / "vite").mkdir(parents=True)
            payload = {
                "dependencies": {"@paddle/paddle-js": "^1.0.0", "vite": "^5.0.0"},
                "devDependencies": {"@types/node": "^20.0.0"},
            }

            missing = _frontend_missing_direct_dependency(frontend_cwd=frontend, payload=payload)

            self.assertEqual(missing, "@paddle/paddle-js")

    def test_frontend_install_commands_uses_lockfile_specific_safe_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            frontend = Path(tmpdir)
            self.assertEqual(
                _frontend_install_commands(frontend_cwd=frontend, manager="npm"),
                (["npm", "install", "--include=dev"], None),
            )

            (frontend / "package-lock.json").write_text("{}", encoding="utf-8")
            self.assertEqual(
                _frontend_install_commands(frontend_cwd=frontend, manager="npm"),
                (
                    ["npm", "ci", "--include=dev", "--prefer-offline", "--no-audit"],
                    ["npm", "install", "--include=dev"],
                ),
            )

    def test_prepare_frontend_runtime_missing_dependency_error_is_actionable(self) -> None:
        class _RuntimeStub:
            def __init__(self) -> None:
                self.config = SimpleNamespace(raw={})
                self.env: dict[str, str] = {}
                self.events: list[dict[str, object]] = []

            def _command_exists(self, executable: str) -> bool:
                return executable == "npm"

            def _emit(self, event: str, **payload: object) -> None:
                self.events.append({"event": event, **payload})

        with tempfile.TemporaryDirectory() as tmpdir:
            frontend = Path(tmpdir)
            (frontend / "node_modules" / "vite").mkdir(parents=True)
            (frontend / "node_modules" / ".bin").mkdir(parents=True)
            (frontend / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {"dev": "vite"},
                        "dependencies": {"@paddle/paddle-js": "^1.0.0"},
                        "devDependencies": {"vite": "^5.0.0"},
                    }
                ),
                encoding="utf-8",
            )
            runtime = _RuntimeStub()

            with self.assertRaisesRegex(RuntimeError, "@paddle/paddle-js.*npm install --include=dev"):
                _prepare_frontend_runtime(
                    runtime,
                    context=SimpleNamespace(name="Main", root=frontend.parent),
                    frontend_cwd=frontend,
                    frontend_log_path="",
                    project_env_base={},
                    frontend_env_file=None,
                    backend_port=8000,
                )

    def test_prepare_frontend_runtime_bypasses_dependency_check_when_requested(self) -> None:
        class _RuntimeStub:
            def __init__(self) -> None:
                self.config = SimpleNamespace(raw={})
                self.env = {"ENVCTL_SKIP_FRONTEND_DEPENDENCY_CHECK": "true"}
                self.events: list[dict[str, object]] = []
                self.process_runner = SimpleNamespace()

            def _command_exists(self, executable: str) -> bool:
                return executable == "npm"

            def _command_env(self, *, port: int, extra=None):  # noqa: ANN001
                _ = port
                env = {}
                env.update(extra or {})
                return env

            def _emit(self, event: str, **payload: object) -> None:
                self.events.append({"event": event, **payload})

            def _read_env_file_safe(self, path: Path) -> dict[str, str]:
                return _read_env_file_safe(path)

            def _run_frontend_bootstrap_command(self, **kwargs) -> None:  # noqa: ANN003
                self.events.append({"event": "bootstrap_command", "command": kwargs["command"]})

        with tempfile.TemporaryDirectory() as tmpdir:
            frontend = Path(tmpdir)
            (frontend / "node_modules" / ".bin").mkdir(parents=True)
            (frontend / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {"dev": "vite"},
                        "dependencies": {"@paddle/paddle-js": "^1.0.0"},
                        "devDependencies": {"vite": "^5.0.0"},
                    }
                ),
                encoding="utf-8",
            )
            runtime = _RuntimeStub()

            _prepare_frontend_runtime(
                runtime,
                context=SimpleNamespace(name="Main", root=frontend.parent),
                frontend_cwd=frontend,
                frontend_log_path="",
                project_env_base={},
                frontend_env_file=None,
                backend_port=8000,
            )

            self.assertFalse(
                any(event.get("event") == "service.bootstrap.dependency_check" for event in runtime.events)
            )


if __name__ == "__main__":
    unittest.main()
