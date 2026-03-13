from __future__ import annotations

import shlex
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_resolution import (  # type: ignore[attr-defined]
    CommandResolutionError,
    resolve_requirement_start_command,
    resolve_service_start_command,
    suggest_service_directory,
    suggest_service_start_command,
)


class CommandResolutionTests(unittest.TestCase):
    def test_configured_backend_command_accepts_relative_python_from_backend_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = root / "backend"
            (backend / "venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend / "venv" / "bin" / "python").write_text("", encoding="utf-8")

            result = resolve_service_start_command(
                service_name="backend",
                project_root=root,
                port=8000,
                env={},
                config_raw={
                    "BACKEND_DIR": "backend",
                    "ENVCTL_BACKEND_START_CMD": "venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port {port}",
                },
                command_exists=lambda exe: exe == "python3",
            )

            self.assertEqual(result.source, "configured")
            self.assertEqual(result.command[0], "venv/bin/python")
            self.assertIn("8000", result.command)

    def test_configured_frontend_command_accepts_relative_python_from_frontend_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            frontend = root / "frontend"
            (frontend / "venv" / "bin").mkdir(parents=True, exist_ok=True)
            (frontend / "venv" / "bin" / "python").write_text("", encoding="utf-8")

            result = resolve_service_start_command(
                service_name="frontend",
                project_root=root,
                port=9000,
                env={},
                config_raw={
                    "FRONTEND_DIR": "frontend",
                    "ENVCTL_FRONTEND_START_CMD": "venv/bin/python app.py",
                },
                command_exists=lambda exe: exe == "python3",
            )

            self.assertEqual(result.source, "configured")
            self.assertEqual(result.command, ["venv/bin/python", "app.py"])

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
            self.assertEqual(result.command[3:], ["--", "--port", "9000", "--host", "127.0.0.1"])

    def test_service_resolution_autodetects_plain_python_backend_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir(parents=True, exist_ok=True)
            (root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
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
            self.assertEqual(result.command[1], "src/main.py")

    def test_suggest_service_start_command_returns_template_for_fastapi_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            (root / "src").mkdir(parents=True, exist_ok=True)
            (root / "src" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
            (root / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (root / ".venv" / "bin" / "python").write_text("", encoding="utf-8")

            command = suggest_service_start_command(
                service_name="backend",
                project_root=root,
                command_exists=lambda exe: True,
            )

            self.assertEqual(
                command,
                shlex.join(["python", "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "{port}"]),
            )

    def test_suggest_service_directory_prefers_src_for_python_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir(parents=True, exist_ok=True)
            (root / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")

            directory = suggest_service_directory(service_name="backend", project_root=root)

            self.assertEqual(directory, "src")

    def test_suggest_service_directory_prefers_frontend_dir_with_package_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            frontend = root / "frontend"
            frontend.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"demo","scripts":{"dev":"vite --host"}}',
                encoding="utf-8",
            )

            directory = suggest_service_directory(service_name="frontend", project_root=root)

            self.assertEqual(directory, "frontend")

    def test_suggest_service_directory_returns_root_for_root_frontend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "package.json").write_text(
                '{"name":"demo","scripts":{"dev":"vite --host"}}',
                encoding="utf-8",
            )

            directory = suggest_service_directory(service_name="frontend", project_root=root)

            self.assertEqual(directory, ".")

    def test_suggest_service_start_command_returns_template_for_vite_frontend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            frontend = root / "frontend"
            frontend.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"demo","scripts":{"dev":"vite --host"}}',
                encoding="utf-8",
            )
            (frontend / "bun.lockb").write_text("", encoding="utf-8")

            command = suggest_service_start_command(
                service_name="frontend",
                project_root=root,
                command_exists=lambda exe: True,
            )

            self.assertEqual(
                command,
                shlex.join(["bun", "run", "dev", "--", "--port", "{port}", "--host", "127.0.0.1"]),
            )

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
                    env={},
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
