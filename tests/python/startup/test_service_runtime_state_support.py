from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from envctl_engine.startup.service_runtime_state_support import (
    _backend_dependency_install_required,
    _backend_runtime_prep_required,
    _frontend_runtime_prep_required,
    _read_backend_bootstrap_state,
    _write_backend_bootstrap_state,
    _write_backend_runtime_prep_state,
    _write_frontend_runtime_prep_state,
)


class ServiceRuntimeStateSupportTests(unittest.TestCase):
    def test_backend_dependency_install_reuses_matching_state(self) -> None:
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
            self.assertEqual(_read_backend_bootstrap_state(backend), state)

    def test_backend_runtime_prep_detects_env_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backend = Path(tmpdir)
            (backend / "requirements.txt").write_text("fastapi==1.0.0\n", encoding="utf-8")
            env_file = backend / ".env"
            env_file.write_text("DATABASE_URL=postgres://one\n", encoding="utf-8")

            required, _reason, state = _backend_runtime_prep_required(
                backend_cwd=backend,
                manager="pip",
                env={"DATABASE_URL": "postgres://one"},
                backend_env_file=env_file,
                backend_env_is_default=True,
                skip_local_db_env=False,
                migrations_enabled=False,
            )
            self.assertTrue(required)
            _write_backend_runtime_prep_state(backend_cwd=backend, state=state)

            required_again, reason_again, _state_again = _backend_runtime_prep_required(
                backend_cwd=backend,
                manager="pip",
                env={"DATABASE_URL": "postgres://two"},
                backend_env_file=env_file,
                backend_env_is_default=True,
                skip_local_db_env=False,
                migrations_enabled=False,
            )

            self.assertTrue(required_again)
            self.assertEqual(reason_again, "env_changed")

    def test_frontend_runtime_prep_reuses_matching_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            frontend = Path(tmpdir)
            (frontend / "package.json").write_text('{"scripts":{"dev":"vite"}}\n', encoding="utf-8")

            required, _reason, state = _frontend_runtime_prep_required(
                frontend_cwd=frontend,
                manager="npm",
                env={"VITE_BACKEND_URL": "http://127.0.0.1:8000"},
                dev_script="dev",
            )
            self.assertTrue(required)
            _write_frontend_runtime_prep_state(frontend_cwd=frontend, state=state)

            required_again, reason_again, state_again = _frontend_runtime_prep_required(
                frontend_cwd=frontend,
                manager="npm",
                env={"VITE_BACKEND_URL": "http://127.0.0.1:8000"},
                dev_script="dev",
            )

            self.assertFalse(required_again)
            self.assertEqual(reason_again, "service_stale_only")
            self.assertEqual(state_again, state)


if __name__ == "__main__":
    unittest.main()
