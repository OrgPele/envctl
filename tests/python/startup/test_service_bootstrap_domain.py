from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.startup.service_bootstrap_domain import (
    _backend_async_driver_mismatch_error,
    _backend_dependency_install_required,
    _backend_migration_retry_env_for_async_driver_mismatch,
    _read_backend_bootstrap_state,
    _read_env_file_safe,
    _resolve_backend_env_contract,
    _resolve_backend_env_file,
    _resolve_frontend_env_file,
    _rewrite_database_url_to_asyncpg,
    _write_backend_bootstrap_state,
)


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


class ServiceBootstrapDomainTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
