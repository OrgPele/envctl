from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from envctl_engine.startup.service_bootstrap_domain import (
    _backend_dependency_install_required,
    _read_backend_bootstrap_state,
    _write_backend_bootstrap_state,
)


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
            (backend / "requirements.txt").write_text("fastapi==0.1.0\n", encoding="utf-8")
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
            requirements.write_text("fastapi==0.1.0\n", encoding="utf-8")
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
            (backend / "requirements.txt").write_text("fastapi==0.1.0\n", encoding="utf-8")

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


if __name__ == "__main__":
    unittest.main()
