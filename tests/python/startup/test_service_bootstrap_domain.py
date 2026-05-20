from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from envctl_engine.startup.protocols import ProjectContextLike
from envctl_engine.startup.service_bootstrap_domain import (
    _backend_async_driver_mismatch_error,
    _backend_dependency_install_required,
    _backend_migrations_enabled,
    _backend_runtime_prep_required,
    _frontend_missing_direct_dependency,
    _prepare_frontend_runtime,
    _prepare_backend_runtime,
    _backend_migration_retry_env_for_async_driver_mismatch,
    _read_backend_bootstrap_state,
    _read_env_file_safe,
    _resolve_backend_env_contract,
    _resolve_backend_env_file,
    _resolve_frontend_env_file,
    _run_backend_migration_step,
    _rewrite_database_url_to_asyncpg,
    _service_env_from_file,
    _sync_backend_env_file,
    _env_assignment_key,
    _write_backend_bootstrap_state,
    _write_backend_runtime_prep_state,
)
from envctl_engine.test_output.parser_base import strip_ansi


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


class _FakeRuntime:
    def __init__(self, *, repo_root: Path, env: dict[str, str] | None = None) -> None:
        self.config = SimpleNamespace(base_dir=repo_root, raw={})
        self.env = dict(env or {})
        self.events: list[dict[str, object]] = []

    def _command_override_value(self, key: str) -> str | None:
        raw = self.env.get(key)
        if not isinstance(raw, str) or not raw.strip():
            return None
        return raw

    def _read_env_file_safe(self, path: Path) -> dict[str, str]:
        return _read_env_file_safe(path)

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append({"event": event, **payload})

    _backend_async_driver_mismatch_error = staticmethod(_backend_async_driver_mismatch_error)
    _rewrite_database_url_to_asyncpg = staticmethod(_rewrite_database_url_to_asyncpg)
    _env_assignment_key = staticmethod(_env_assignment_key)


class ServiceBootstrapDomainTests(unittest.TestCase):
    def test_frontend_missing_direct_dependency_detects_declared_package_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            frontend = Path(tmpdir)
            (frontend / "node_modules" / "vite").mkdir(parents=True)
            payload = {
                "dependencies": {"@paddle/paddle-js": "^1.0.0", "vite": "^5.0.0"},
                "devDependencies": {"@types/node": "^20.0.0"},
            }

            missing = _frontend_missing_direct_dependency(frontend_cwd=frontend, payload=payload)

            self.assertEqual(missing, "@paddle/paddle-js")

    def test_frontend_missing_direct_dependency_can_pass_scoped_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            frontend = Path(tmpdir)
            (frontend / "node_modules" / "@paddle" / "paddle-js").mkdir(parents=True)
            payload = {"dependencies": {"@paddle/paddle-js": "^1.0.0"}}

            missing = _frontend_missing_direct_dependency(frontend_cwd=frontend, payload=payload)

            self.assertIsNone(missing)

    def test_frontend_missing_direct_dependency_skips_absent_node_modules_for_bootstrap_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            frontend = Path(tmpdir)
            payload = {"dependencies": {"@paddle/paddle-js": "^1.0.0"}}

            missing = _frontend_missing_direct_dependency(frontend_cwd=frontend, payload=payload)

            self.assertIsNone(missing)

    def test_frontend_missing_direct_dependency_checks_dev_dependencies_needed_by_vite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            frontend = Path(tmpdir)
            (frontend / "node_modules" / "vite").mkdir(parents=True)
            payload = {"devDependencies": {"vite": "^5.0.0", "@vitejs/plugin-react": "^4.0.0"}}

            missing = _frontend_missing_direct_dependency(frontend_cwd=frontend, payload=payload)

            self.assertEqual(missing, "@vitejs/plugin-react")

    def test_frontend_missing_direct_dependency_ignores_types_packages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            frontend = Path(tmpdir)
            (frontend / "node_modules").mkdir(parents=True)
            payload = {"devDependencies": {"@types/react": "^18.0.0"}}

            missing = _frontend_missing_direct_dependency(frontend_cwd=frontend, payload=payload)

            self.assertIsNone(missing)

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

    def test_backend_dependency_install_required_when_state_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = Path(tmpdir)
            (backend / "pyproject.toml").write_text("[tool.poetry]\nname='x'\n", encoding="utf-8")
            (backend / "venv").mkdir()

            required, reason, state = _backend_dependency_install_required(
                backend_cwd=backend,
                manager="poetry",
            )

            self.assertTrue(required)
            self.assertEqual(reason, "dependency_files_changed")
            self.assertEqual(state["manager"], "poetry")

    def test_backend_dependency_install_not_required_when_state_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = Path(tmpdir)
            (backend / "requirements.txt").write_text("fastapi==1.0.0\n", encoding="utf-8")
            (backend / "venv").mkdir()

            required, _reason, state = _backend_dependency_install_required(
                backend_cwd=backend,
                manager="pip",
            )
            self.assertTrue(required)
            _write_backend_bootstrap_state(backend_cwd=backend, state=state)

            required_again, reason_again, state_again = _backend_dependency_install_required(
                backend_cwd=backend,
                manager="pip",
            )

            self.assertFalse(required_again)
            self.assertEqual(reason_again, "up_to_date")
            self.assertEqual(state_again, state)

    def test_backend_dependency_install_required_when_dependency_files_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = Path(tmpdir)
            requirements = backend / "requirements.txt"
            requirements.write_text("fastapi==1.0.0\n", encoding="utf-8")
            (backend / "venv").mkdir()

            _required, _reason, state = _backend_dependency_install_required(
                backend_cwd=backend,
                manager="pip",
            )
            _write_backend_bootstrap_state(backend_cwd=backend, state=state)
            requirements.write_text("fastapi==0.2.0\n", encoding="utf-8")

            required_again, reason_again, _state_again = _backend_dependency_install_required(
                backend_cwd=backend,
                manager="pip",
            )

            self.assertTrue(required_again)
            self.assertEqual(reason_again, "dependency_files_changed")

    def test_backend_dependency_install_required_when_environment_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = Path(tmpdir)
            (backend / "requirements.txt").write_text("fastapi==1.0.0\n", encoding="utf-8")

            required, reason, _state = _backend_dependency_install_required(
                backend_cwd=backend,
                manager="pip",
            )

            self.assertTrue(required)
            self.assertEqual(reason, "environment_missing")

    def test_backend_dependency_install_required_for_cached_poetry_when_runtime_dependency_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = Path(tmpdir)
            (backend / "pyproject.toml").write_text(
                "[tool.poetry]\nname='x'\n[tool.poetry.dependencies]\nuvicorn='^0.24.0'\n",
                encoding="utf-8",
            )

            _required, _reason, state = _backend_dependency_install_required(
                backend_cwd=backend,
                manager="poetry",
                environment_ready=lambda: False,
            )
            _write_backend_bootstrap_state(backend_cwd=backend, state=state)

            required_again, reason_again, state_again = _backend_dependency_install_required(
                backend_cwd=backend,
                manager="poetry",
                environment_ready=lambda: False,
            )

            self.assertTrue(required_again)
            self.assertEqual(reason_again, "poetry_environment_missing_dependencies")
            self.assertEqual(state_again, state)

    def test_backend_dependency_install_skips_cached_poetry_when_runtime_dependency_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = Path(tmpdir)
            (backend / "pyproject.toml").write_text(
                "[tool.poetry]\nname='x'\n[tool.poetry.dependencies]\nuvicorn='^0.24.0'\n",
                encoding="utf-8",
            )

            _required, _reason, state = _backend_dependency_install_required(
                backend_cwd=backend,
                manager="poetry",
                environment_ready=lambda: False,
            )
            _write_backend_bootstrap_state(backend_cwd=backend, state=state)

            required_again, reason_again, state_again = _backend_dependency_install_required(
                backend_cwd=backend,
                manager="poetry",
                environment_ready=lambda: True,
            )

            self.assertFalse(required_again)
            self.assertEqual(reason_again, "up_to_date")
            self.assertEqual(state_again, state)

    def test_prepare_backend_runtime_rechecks_cached_poetry_dependencies_before_reusing_runtime(self) -> None:
        class _Context:
            def __init__(self, *, root: Path) -> None:
                self.name = "Main"
                self.root = root

        class _ProbeProcessRunner:
            def __init__(self) -> None:
                self.run_calls: list[tuple[str, ...]] = []

            def run(self, command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                self.run_calls.append(tuple(command))
                if tuple(command[:4]) == ("poetry", "run", "python", "-c"):
                    return SimpleNamespace(returncode=1, stdout="", stderr="No module named uvicorn")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

        class _RuntimeStub:
            def __init__(self, repo_root: Path) -> None:
                self.config = SimpleNamespace(base_dir=repo_root, raw={})
                self.env: dict[str, str] = {}
                self.events: list[dict[str, object]] = []
                self.bootstrap_commands: list[list[str]] = []
                self.process_runner = _ProbeProcessRunner()

            def _command_exists(self, command: str) -> bool:
                return command == "poetry"

            def _command_env(self, *, port: int, extra=None):  # noqa: ANN001
                _ = port, extra
                return {}

            def _command_override_value(self, key: str) -> str | None:
                _ = key
                return None

            def _read_env_file_safe(self, path: Path) -> dict[str, str]:
                return _read_env_file_safe(path)

            def _sync_backend_env_file(self, path: Path, *, env):  # noqa: ANN001
                _ = path, env

            def _emit(self, event: str, **payload: object) -> None:
                self.events.append({"event": event, **payload})

            def _backend_has_migrations(self, backend_cwd: Path) -> bool:
                _ = backend_cwd
                return False

            def _run_backend_bootstrap_command(self, **kwargs) -> None:  # noqa: ANN003
                self.bootstrap_commands.append(list(kwargs["command"]))

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            backend = repo / "backend"
            backend.mkdir(parents=True)
            (backend / "pyproject.toml").write_text(
                "[tool.poetry]\nname='x'\n[tool.poetry.dependencies]\nuvicorn='^0.24.0'\n",
                encoding="utf-8",
            )
            _required, _reason, dependency_state = _backend_dependency_install_required(
                backend_cwd=backend,
                manager="poetry",
                environment_ready=lambda: True,
            )
            _write_backend_bootstrap_state(backend_cwd=backend, state=dependency_state)
            _runtime_required, _runtime_reason, runtime_state = _backend_runtime_prep_required(
                backend_cwd=backend,
                manager="poetry",
                env={},
                backend_env_file=None,
                backend_env_is_default=False,
                skip_local_db_env=False,
                migrations_enabled=False,
            )
            _write_backend_runtime_prep_state(backend_cwd=backend, state=runtime_state)
            runtime = _RuntimeStub(repo)

            _prepare_backend_runtime(
                runtime,
                context=_Context(root=repo),
                backend_cwd=backend,
                backend_log_path="",
                project_env_base={},
                route=None,
                backend_env_file=None,
                backend_env_is_default=False,
            )

            self.assertIn(["poetry", "install"], runtime.bootstrap_commands)
            self.assertTrue(
                any(event.get("reason") == "poetry_environment_missing_dependencies" for event in runtime.events)
            )

    def test_backend_bootstrap_state_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = Path(tmpdir)
            state = {"manager": "pip", "fingerprint": "abc"}

            _write_backend_bootstrap_state(backend_cwd=backend, state=state)

            self.assertEqual(_read_backend_bootstrap_state(backend), state)

    def test_resolve_backend_env_file_accepts_absolute_override_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            override_file = repo / "config" / "backend.override.env"
            backend_dir.mkdir(parents=True, exist_ok=True)
            override_file.parent.mkdir(parents=True, exist_ok=True)
            override_file.write_text("CUSTOM=1\n", encoding="utf-8")

            runtime = _FakeRuntime(repo_root=repo, env={"BACKEND_ENV_FILE_OVERRIDE": str(override_file)})
            context = SimpleNamespace(name="feature-a-1", root=backend_dir.parent)

            resolved, is_default = _resolve_backend_env_file(
                runtime,
                context=context,
                backend_cwd=backend_dir,
            )

            self.assertEqual(resolved, override_file.resolve())
            self.assertFalse(is_default)

    def test_resolve_backend_env_file_prefers_target_root_relative_candidate_when_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            tree_root = repo / "trees" / "feature-a" / "1"
            backend_dir = tree_root / "backend"
            override_file = tree_root / "config" / "backend.override.env"
            backend_dir.mkdir(parents=True, exist_ok=True)
            override_file.parent.mkdir(parents=True, exist_ok=True)
            override_file.write_text("CUSTOM=tree\n", encoding="utf-8")

            runtime = _FakeRuntime(repo_root=repo, env={"BACKEND_ENV_FILE_OVERRIDE": "config/backend.override.env"})
            context = SimpleNamespace(name="feature-a-1", root=tree_root)

            resolved, is_default = _resolve_backend_env_file(
                runtime,
                context=context,
                backend_cwd=backend_dir,
            )

            self.assertEqual(resolved, override_file.resolve())
            self.assertFalse(is_default)

    def test_resolve_backend_env_file_accepts_repo_root_relative_candidate_when_unique(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            tree_root = repo / "trees" / "feature-a" / "1"
            backend_dir = tree_root / "backend"
            override_file = repo / "config" / "backend.override.env"
            backend_dir.mkdir(parents=True, exist_ok=True)
            override_file.parent.mkdir(parents=True, exist_ok=True)
            override_file.write_text("CUSTOM=repo\n", encoding="utf-8")

            runtime = _FakeRuntime(repo_root=repo, env={"BACKEND_ENV_FILE_OVERRIDE": "config/backend.override.env"})
            context = SimpleNamespace(name="feature-a-1", root=tree_root)

            resolved, is_default = _resolve_backend_env_file(
                runtime,
                context=context,
                backend_cwd=backend_dir,
            )

            self.assertEqual(resolved, override_file.resolve())
            self.assertFalse(is_default)

    def test_resolve_backend_env_file_rejects_ambiguous_relative_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            tree_root = repo / "trees" / "feature-a" / "1"
            backend_dir = tree_root / "backend"
            repo_override = repo / "config" / "backend.override.env"
            tree_override = tree_root / "config" / "backend.override.env"
            backend_dir.mkdir(parents=True, exist_ok=True)
            repo_override.parent.mkdir(parents=True, exist_ok=True)
            tree_override.parent.mkdir(parents=True, exist_ok=True)
            repo_override.write_text("CUSTOM=repo\n", encoding="utf-8")
            tree_override.write_text("CUSTOM=tree\n", encoding="utf-8")

            runtime = _FakeRuntime(repo_root=repo, env={"BACKEND_ENV_FILE_OVERRIDE": "config/backend.override.env"})
            context = SimpleNamespace(name="feature-a-1", root=tree_root)

            with self.assertRaisesRegex(RuntimeError, "ambiguous"):
                _resolve_backend_env_file(
                    runtime,
                    context=context,
                    backend_cwd=backend_dir,
                )

    def test_resolve_backend_env_file_falls_back_to_default_backend_dot_env_when_override_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            tree_root = repo / "trees" / "feature-a" / "1"
            backend_dir = tree_root / "backend"
            default_env = backend_dir / ".env"
            backend_dir.mkdir(parents=True, exist_ok=True)
            default_env.write_text("DEFAULT=1\n", encoding="utf-8")

            runtime = _FakeRuntime(repo_root=repo, env={"BACKEND_ENV_FILE_OVERRIDE": "config/missing.env"})
            context = SimpleNamespace(name="feature-a-1", root=tree_root)

            resolved, is_default = _resolve_backend_env_file(
                runtime,
                context=context,
                backend_cwd=backend_dir,
            )

            self.assertEqual(resolved, default_env.resolve())
            self.assertTrue(is_default)

    def test_resolve_frontend_env_file_uses_shared_repo_relative_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            tree_root = repo / "trees" / "feature-a" / "1"
            frontend_dir = tree_root / "frontend"
            override_file = repo / "config" / "frontend.override.env"
            frontend_dir.mkdir(parents=True, exist_ok=True)
            override_file.parent.mkdir(parents=True, exist_ok=True)
            override_file.write_text("CUSTOM=frontend\n", encoding="utf-8")

            runtime = _FakeRuntime(repo_root=repo, env={"FRONTEND_ENV_FILE_OVERRIDE": "config/frontend.override.env"})
            context = SimpleNamespace(name="feature-a-1", root=tree_root)

            resolved = _resolve_frontend_env_file(
                runtime,
                context=context,
                frontend_cwd=frontend_dir,
            )

            self.assertEqual(resolved, override_file.resolve())

    def test_resolve_frontend_env_file_rejects_ambiguous_relative_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            tree_root = repo / "trees" / "feature-a" / "1"
            frontend_dir = tree_root / "frontend"
            repo_override = repo / "config" / "frontend.override.env"
            tree_override = tree_root / "config" / "frontend.override.env"
            frontend_dir.mkdir(parents=True, exist_ok=True)
            repo_override.parent.mkdir(parents=True, exist_ok=True)
            tree_override.parent.mkdir(parents=True, exist_ok=True)
            repo_override.write_text("CUSTOM=repo\n", encoding="utf-8")
            tree_override.write_text("CUSTOM=tree\n", encoding="utf-8")

            runtime = _FakeRuntime(repo_root=repo, env={"FRONTEND_ENV_FILE_OVERRIDE": "config/frontend.override.env"})
            context = SimpleNamespace(name="feature-a-1", root=tree_root)

            with self.assertRaisesRegex(RuntimeError, "ambiguous"):
                _resolve_frontend_env_file(
                    runtime,
                    context=context,
                    frontend_cwd=frontend_dir,
                )

    def test_resolve_frontend_env_file_falls_back_to_default_frontend_dot_env_when_override_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            tree_root = repo / "trees" / "feature-a" / "1"
            frontend_dir = tree_root / "frontend"
            default_env = frontend_dir / ".env"
            frontend_dir.mkdir(parents=True, exist_ok=True)
            default_env.write_text("DEFAULT=1\n", encoding="utf-8")

            runtime = _FakeRuntime(repo_root=repo, env={"FRONTEND_ENV_FILE_OVERRIDE": "config/missing.env"})
            context = SimpleNamespace(name="feature-a-1", root=tree_root)

            resolved = _resolve_frontend_env_file(
                runtime,
                context=context,
                frontend_cwd=frontend_dir,
            )

            self.assertEqual(resolved, default_env.resolve())

    def test_resolve_backend_env_contract_scrubs_inherited_backend_keys_and_reapplies_projection_for_default_env(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            tree_root = repo / "trees" / "feature-a" / "1"
            backend_dir = tree_root / "backend"
            env_file = backend_dir / ".env"
            backend_dir.mkdir(parents=True, exist_ok=True)
            env_file.write_text(
                "DATABASE_URL=postgresql://legacy\n"
                "SQLALCHEMY_DATABASE_URL=postgresql://legacy\n"
                "ASYNC_DATABASE_URL=postgresql://legacy\n"
                "REDIS_URL=redis://legacy\n"
                "CUSTOM_BACKEND_FLAG=enabled\n",
                encoding="utf-8",
            )
            runtime = _FakeRuntime(repo_root=repo)
            context = SimpleNamespace(name="feature-a-1", root=tree_root)

            result = _resolve_backend_env_contract(
                runtime,
                context=context,
                backend_cwd=backend_dir,
                base_env={
                    "APP_ENV_FILE": "/tmp/leaked.env",
                    "DATABASE_URL": "postgresql://shell",
                    "SQLALCHEMY_DATABASE_URL": "postgresql://shell",
                    "ASYNC_DATABASE_URL": "postgresql://shell",
                    "DB_HOST": "shell-db.internal",
                    "PATH": "/usr/bin",
                    "SHELL_ONLY": "1",
                },
                projected_env={
                    "DATABASE_URL": "postgresql+asyncpg://svc_user:svc_pass@localhost:5544/svc_db",
                    "SQLALCHEMY_DATABASE_URL": "postgresql+asyncpg://svc_user:svc_pass@localhost:5544/svc_db",
                    "ASYNC_DATABASE_URL": "postgresql+asyncpg://svc_user:svc_pass@localhost:5544/svc_db",
                    "REDIS_URL": "redis://localhost:6399/0",
                    "DB_HOST": "localhost",
                    "DB_PORT": "5544",
                },
            )

            self.assertEqual(result.env["APP_ENV_FILE"], str(env_file.resolve()))
            self.assertEqual(
                result.env["DATABASE_URL"],
                "postgresql+asyncpg://svc_user:svc_pass@localhost:5544/svc_db",
            )
            self.assertEqual(
                result.env["SQLALCHEMY_DATABASE_URL"],
                "postgresql+asyncpg://svc_user:svc_pass@localhost:5544/svc_db",
            )
            self.assertEqual(
                result.env["ASYNC_DATABASE_URL"],
                "postgresql+asyncpg://svc_user:svc_pass@localhost:5544/svc_db",
            )
            self.assertEqual(result.env["REDIS_URL"], "redis://localhost:6399/0")
            self.assertEqual(result.env["DB_HOST"], "localhost")
            self.assertEqual(result.env["CUSTOM_BACKEND_FLAG"], "enabled")
            self.assertEqual(result.env["SHELL_ONLY"], "1")
            self.assertCountEqual(
                result.scrubbed_keys,
                (
                    "APP_ENV_FILE",
                    "ASYNC_DATABASE_URL",
                    "DATABASE_URL",
                    "DB_HOST",
                    "SQLALCHEMY_DATABASE_URL",
                ),
            )
            self.assertTrue(any(event.get("event") == "backend.env.resolved" for event in runtime.events))

    def test_default_backend_env_keeps_stale_redis_url_out_of_persistence_but_not_launch_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            tree_root = repo / "trees" / "feature-a" / "1"
            backend_dir = tree_root / "backend"
            env_file = backend_dir / ".env"
            backend_dir.mkdir(parents=True, exist_ok=True)
            env_file.write_text(
                "REDIS_URL=redis://localhost:6518/0\nCUSTOM_BACKEND_FLAG=enabled\n",
                encoding="utf-8",
            )
            runtime = _FakeRuntime(repo_root=repo)
            context = SimpleNamespace(name="feature-a-1", root=tree_root)

            result = _resolve_backend_env_contract(
                runtime,
                context=context,
                backend_cwd=backend_dir,
                base_env={},
                projected_env={"REDIS_URL": "redis://localhost:6603/0"},
            )
            _sync_backend_env_file(runtime, env_file, env=result.env)

            self.assertEqual(result.env["REDIS_URL"], "redis://localhost:6603/0")
            content = env_file.read_text(encoding="utf-8")
            self.assertIn("REDIS_URL=redis://localhost:6518/0", content)
            self.assertIn("CUSTOM_BACKEND_FLAG=enabled", content)
            self.assertNotIn("REDIS_URL=redis://localhost:6603/0", content)

    def test_resolve_backend_env_contract_keeps_explicit_override_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            tree_root = repo / "trees" / "feature-a" / "1"
            backend_dir = tree_root / "backend"
            override_file = repo / "config" / "backend.override.env"
            backend_dir.mkdir(parents=True, exist_ok=True)
            override_file.parent.mkdir(parents=True, exist_ok=True)
            override_file.write_text(
                "DATABASE_URL=postgresql+psycopg2://override_user:override_pass@db.internal/override_db\n"
                "SQLALCHEMY_DATABASE_URL=postgresql+psycopg2://override_user:override_pass@db.internal/override_db\n"
                "ASYNC_DATABASE_URL=postgresql+psycopg2://override_user:override_pass@db.internal/override_db\n",
                encoding="utf-8",
            )
            runtime = _FakeRuntime(repo_root=repo, env={"BACKEND_ENV_FILE_OVERRIDE": str(override_file)})
            context = SimpleNamespace(name="feature-a-1", root=tree_root)

            result = _resolve_backend_env_contract(
                runtime,
                context=context,
                backend_cwd=backend_dir,
                base_env={},
                projected_env={
                    "DATABASE_URL": "postgresql+asyncpg://svc_user:svc_pass@localhost:5544/svc_db",
                    "SQLALCHEMY_DATABASE_URL": "postgresql+asyncpg://svc_user:svc_pass@localhost:5544/svc_db",
                    "ASYNC_DATABASE_URL": "postgresql+asyncpg://svc_user:svc_pass@localhost:5544/svc_db",
                },
            )

            self.assertEqual(
                result.env["DATABASE_URL"],
                "postgresql+psycopg2://override_user:override_pass@db.internal/override_db",
            )
            self.assertEqual(
                result.env["SQLALCHEMY_DATABASE_URL"],
                "postgresql+psycopg2://override_user:override_pass@db.internal/override_db",
            )
            self.assertEqual(
                result.env["ASYNC_DATABASE_URL"],
                "postgresql+psycopg2://override_user:override_pass@db.internal/override_db",
            )
            self.assertTrue(result.override_authoritative)
            self.assertEqual(result.env_file_source, "explicit_override")

    def test_explicit_backend_env_override_remains_authoritative_for_redis_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            tree_root = repo / "trees" / "feature-a" / "1"
            backend_dir = tree_root / "backend"
            override_file = repo / "config" / "backend.override.env"
            backend_dir.mkdir(parents=True, exist_ok=True)
            override_file.parent.mkdir(parents=True, exist_ok=True)
            override_file.write_text(
                "REDIS_URL=redis://cache.example.test:6382/0\nCUSTOM_BACKEND_FLAG=override-enabled\n",
                encoding="utf-8",
            )
            runtime = _FakeRuntime(repo_root=repo, env={"BACKEND_ENV_FILE_OVERRIDE": str(override_file)})
            context = SimpleNamespace(name="feature-a-1", root=tree_root)

            result = _resolve_backend_env_contract(
                runtime,
                context=context,
                backend_cwd=backend_dir,
                base_env={},
                projected_env={"REDIS_URL": "redis://localhost:6603/0"},
            )

            self.assertEqual(result.env["REDIS_URL"], "redis://cache.example.test:6382/0")
            self.assertEqual(result.env["CUSTOM_BACKEND_FLAG"], "override-enabled")
            self.assertTrue(result.override_authoritative)
            self.assertEqual(result.env_file_source, "explicit_override")

    def test_backend_migrations_default_to_pre_service_for_normal_startup(self) -> None:
        runtime = _FakeRuntime(repo_root=Path("/tmp/repo"))

        self.assertTrue(_backend_migrations_enabled(runtime, route=None))

    def test_backend_env_contract_disables_app_internal_startup_migrations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            backend_dir = repo / "backend"
            backend_dir.mkdir(parents=True, exist_ok=True)
            runtime = _FakeRuntime(repo_root=repo)
            context = cast(ProjectContextLike, SimpleNamespace(name="Main", root=repo))

            result = _resolve_backend_env_contract(
                runtime,
                context=context,
                backend_cwd=backend_dir,
                base_env={},
                projected_env={},
            )

            self.assertEqual(result.env["RUN_DB_MIGRATIONS_ON_STARTUP"], "false")

    def test_backend_launch_env_disables_app_internal_startup_migrations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "backend.env"
            env_file.write_text("RUN_DB_MIGRATIONS_ON_STARTUP=true\nCUSTOM=1\n", encoding="utf-8")
            runtime = _FakeRuntime(repo_root=Path(tmpdir))

            env = _service_env_from_file(
                runtime,
                base_env={},
                env_file=env_file,
                include_app_env_file=True,
            )

            self.assertEqual(env["RUN_DB_MIGRATIONS_ON_STARTUP"], "false")
            self.assertEqual(env["CUSTOM"], "1")

    def test_backend_launch_env_explicit_file_can_override_projected_database_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "backend.override.env"
            env_file.write_text(
                "DATABASE_URL=postgresql+asyncpg://remote_user:remote_pass@remote.db/prod\n",
                encoding="utf-8",
            )
            runtime = _FakeRuntime(repo_root=Path(tmpdir))

            env = _service_env_from_file(
                runtime,
                base_env={"DATABASE_URL": "postgresql+asyncpg://local_user:local_pass@localhost/local"},
                env_file=env_file,
                include_app_env_file=True,
                env_file_authoritative=True,
            )

            self.assertEqual(env["DATABASE_URL"], "postgresql+asyncpg://remote_user:remote_pass@remote.db/prod")
            self.assertEqual(env["RUN_DB_MIGRATIONS_ON_STARTUP"], "false")

    def test_backend_launch_env_disables_app_internal_startup_migrations_without_env_file(self) -> None:
        runtime = _FakeRuntime(repo_root=Path("/tmp/repo"))

        env = _service_env_from_file(
            runtime,
            base_env={},
            env_file=None,
            include_app_env_file=True,
        )

        self.assertEqual(env["RUN_DB_MIGRATIONS_ON_STARTUP"], "false")

    def test_backend_async_retry_rewrites_entire_db_url_family(self) -> None:
        retry_env = _backend_migration_retry_env_for_async_driver_mismatch(
            _FakeRuntime(repo_root=Path("/tmp")),
            env={
                "DATABASE_URL": "postgresql+psycopg2://svc_user:svc_pass@localhost:5432/svc_db",
                "SQLALCHEMY_DATABASE_URL": "postgresql+psycopg2://svc_user:svc_pass@localhost:5432/svc_db",
                "ASYNC_DATABASE_URL": "postgresql+psycopg2://svc_user:svc_pass@localhost:5432/svc_db",
            },
            error_message="The asyncio extension requires an async driver to be used.",
        )

        self.assertIsNotNone(retry_env)
        assert retry_env is not None
        self.assertEqual(
            retry_env["DATABASE_URL"],
            "postgresql+asyncpg://svc_user:svc_pass@localhost:5432/svc_db",
        )
        self.assertEqual(
            retry_env["SQLALCHEMY_DATABASE_URL"],
            "postgresql+asyncpg://svc_user:svc_pass@localhost:5432/svc_db",
        )
        self.assertEqual(
            retry_env["ASYNC_DATABASE_URL"],
            "postgresql+asyncpg://svc_user:svc_pass@localhost:5432/svc_db",
        )

    def test_backend_migration_warning_hyperlinks_backend_log_path(self) -> None:
        class _RuntimeStub:
            env = {"ENVCTL_UI_HYPERLINK_MODE": "on"}

            @staticmethod
            def _emit(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
                return None

            @staticmethod
            def _backend_migration_retry_env_for_async_driver_mismatch(*, env, error_message):  # noqa: ANN001
                _ = env, error_message
                return None

            @staticmethod
            def _backend_bootstrap_strict() -> bool:
                return False

            @staticmethod
            def _run_backend_bootstrap_command(**kwargs) -> None:  # noqa: ANN003
                raise RuntimeError("migration failed")

        with tempfile.TemporaryDirectory() as tmpdir:
            out = _TtyStringIO()
            with redirect_stdout(out):
                _run_backend_migration_step(
                    _RuntimeStub(),
                    context=type("Ctx", (), {"name": "Main"})(),
                    command=["alembic", "upgrade", "head"],
                    cwd=Path(tmpdir),
                    backend_log_path="/tmp/backend.log",
                    env={},
                    step="alembic upgrade head",
                )

        self.assertIn("\x1b]8;;file://", out.getvalue())
        self.assertIn("/tmp/backend.log", strip_ansi(out.getvalue()))


if __name__ == "__main__":
    unittest.main()
