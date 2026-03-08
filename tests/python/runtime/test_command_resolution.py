from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.command_resolution import (  # type: ignore[attr-defined]
    CommandResolutionError,
    resolve_requirement_start_command,
    resolve_service_start_command,
)


class CommandResolutionTests(unittest.TestCase):
    def test_service_resolution_prefers_backend_venv_python_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = root / "backend"
            (backend / "app").mkdir(parents=True, exist_ok=True)
            (backend / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            (backend / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
            (backend / "venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend / "venv" / "bin" / "python").write_text("", encoding="utf-8")
            (root / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")

            result = resolve_service_start_command(
                service_name="backend",
                project_root=root,
                port=8000,
                env={},
                config_raw={},
                command_exists=lambda exe: True,
            )

            self.assertEqual(result.source, "autodetected")
            self.assertEqual(result.command[0], str(backend / "venv" / "bin" / "python"))

    def test_service_resolution_autodetects_fastapi_backend_from_pyproject(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = root / "backend"
            (backend / "app").mkdir(parents=True, exist_ok=True)
            (backend / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            (backend / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
            (root / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")

            result = resolve_service_start_command(
                service_name="backend",
                project_root=root,
                port=8000,
                env={},
                config_raw={},
                command_exists=lambda exe: True,
            )

            self.assertEqual(result.source, "autodetected")
            self.assertEqual(result.command[0], str(root / ".venv" / "bin" / "python"))
            self.assertIn("-m", result.command)
            self.assertIn("uvicorn", result.command)
            self.assertIn("app.main:app", result.command)
            self.assertIn("8000", result.command)

    def test_service_resolution_autodetects_vite_frontend_from_package_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            frontend = root / "frontend"
            frontend.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"demo","scripts":{"dev":"vite --host"}}',
                encoding="utf-8",
            )
            (frontend / "bun.lockb").write_text("", encoding="utf-8")

            result = resolve_service_start_command(
                service_name="frontend",
                project_root=root,
                port=9000,
                env={},
                config_raw={},
                command_exists=lambda exe: True,
            )

            self.assertEqual(result.source, "autodetected")
            self.assertEqual(result.command[:3], ["bun", "run", "dev"])

    def test_service_resolution_raises_when_unresolvable_and_synthetic_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(CommandResolutionError) as cm:
                resolve_service_start_command(
                    service_name="backend",
                    project_root=root,
                    port=8000,
                    env={},
                    config_raw={},
                    command_exists=lambda exe: True,
                )
        self.assertEqual(cm.exception.code, "missing_service_start_command")
        self.assertIn("autodetect_failed_backend", str(cm.exception))

    def test_service_resolution_rejects_synthetic_envs_and_requires_real_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(CommandResolutionError) as cm:
                resolve_service_start_command(
                    service_name="backend",
                    project_root=root,
                    port=8000,
                    env={
                    },
                    config_raw={},
                    command_exists=lambda exe: True,
                )
        self.assertEqual(cm.exception.code, "missing_service_start_command")

    def test_requirement_resolution_raises_when_unconfigured_and_synthetic_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(CommandResolutionError) as cm:
                resolve_requirement_start_command(
                    service_name="redis",
                    project_root=root,
                    port=6379,
                    env={},
                    config_raw={},
                    command_exists=lambda exe: True,
                )
        self.assertEqual(cm.exception.code, "missing_requirement_start_command")


if __name__ == "__main__":
    unittest.main()
