from __future__ import annotations

from pathlib import Path
import unittest

from envctl_engine.actions.action_failed_test_spec_support import failed_rerun_spec_for_entry
from envctl_engine.actions.action_test_manifest_support import FailedTestManifestEntry


class ActionFailedTestSpecSupportTests(unittest.TestCase):
    def test_backend_pytest_failed_rerun_uses_injected_python_and_backend_normalizer(self) -> None:
        entry = FailedTestManifestEntry(
            source="backend_pytest",
            suite="Backend (pytest)",
            failed_tests=("backend/tests/test_auth.py::test_signup_regression",),
            failed_files=(),
        )

        spec = failed_rerun_spec_for_entry(
            entry,
            project_name="Main",
            project_root=Path("/repo"),
            repo_root=Path("/repo"),
            target_obj=None,
            detect_python_bin_fn=lambda *_roots: "/repo/backend/.venv/bin/python",
            normalize_backend_command_fn=lambda command, _project_root: ["normalized", *command],
        )

        self.assertFalse(isinstance(spec, str))
        self.assertIsNotNone(spec)
        self.assertEqual(
            spec.spec.command,
            [
                "normalized",
                "/repo/backend/.venv/bin/python",
                "-m",
                "pytest",
                "backend/tests/test_auth.py::test_signup_regression",
            ],
        )
        self.assertEqual(spec.resolved_source, "backend_pytest")

    def test_configured_failed_rerun_reports_non_rerunnable_custom_command(self) -> None:
        entry = FailedTestManifestEntry(
            source="configured",
            suite="Custom",
            failed_tests=("tests/test_any.py::test_case",),
            failed_files=(),
        )

        result = failed_rerun_spec_for_entry(
            entry,
            project_name="Main",
            project_root=Path("/repo"),
            repo_root=Path("/repo"),
            target_obj=None,
        )

        self.assertIsInstance(result, str)
        self.assertIn("custom configured command", result)


if __name__ == "__main__":
    unittest.main()
