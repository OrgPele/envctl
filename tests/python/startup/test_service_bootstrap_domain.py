from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from envctl_engine.startup.service_bootstrap_domain import (
    _backend_dependency_install_required,
    _read_backend_bootstrap_state,
    _run_backend_migration_step,
    _write_backend_bootstrap_state,
)
from envctl_engine.test_output.parser_base import strip_ansi


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


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
