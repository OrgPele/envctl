from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.startup.service_backend_migration_support import (
    _backend_async_driver_mismatch_error,
    _backend_migration_retry_env_for_async_driver_mismatch,
    _backend_migrations_enabled,
    _backend_missing_revision_id,
    _run_backend_migration_step,
    _rewrite_database_url_to_asyncpg,
)
from envctl_engine.test_output.parser_base import strip_ansi


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


class ServiceBackendMigrationSupportTests(unittest.TestCase):
    def test_backend_migrations_default_to_pre_service_for_normal_startup(self) -> None:
        runtime = SimpleNamespace(env={}, config=SimpleNamespace(raw={}))

        self.assertTrue(_backend_migrations_enabled(runtime, route=None))

    def test_async_driver_mismatch_retry_rewrites_database_url_family(self) -> None:
        runtime = SimpleNamespace(
            _backend_async_driver_mismatch_error=staticmethod(_backend_async_driver_mismatch_error),
            _rewrite_database_url_to_asyncpg=staticmethod(_rewrite_database_url_to_asyncpg),
        )

        retry_env = _backend_migration_retry_env_for_async_driver_mismatch(
            runtime,
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

    def test_missing_revision_id_extracts_alembic_revision(self) -> None:
        self.assertEqual(
            _backend_missing_revision_id("Can't locate revision identified by 'abc123'"),
            "abc123",
        )

    def test_migration_warning_hyperlinks_backend_log_path(self) -> None:
        class RuntimeStub:
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
                    RuntimeStub(),
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
