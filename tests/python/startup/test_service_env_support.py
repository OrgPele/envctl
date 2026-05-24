from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from envctl_engine.startup.protocols import ProjectContextLike
from envctl_engine.startup.service_env_support import (
    _env_assignment_key,
    _read_env_file_safe,
    _resolve_backend_env_contract,
    _resolve_backend_env_file,
    _resolve_frontend_env_file,
    _service_env_from_file,
    _sync_backend_env_file,
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

    _env_assignment_key = staticmethod(_env_assignment_key)


class ServiceEnvSupportTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
