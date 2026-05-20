from __future__ import annotations

from types import SimpleNamespace
import tempfile
from pathlib import Path
import unittest

from envctl_engine.actions.action_test_support import (
    collect_failed_test_manifest_entries,
    collect_failed_tests,
    collect_generic_suite_failures,
    collect_suite_failure_contexts,
    git_state_components,
    resolve_failed_test_error,
    suite_display_name,
)


class ActionTestSummarySupportTests(unittest.TestCase):
    def test_collect_failed_tests_dedupes_and_resolves_file_level_errors(self) -> None:
        outcomes = [
            {
                "index": 2,
                "project_name": "Main",
                "suite": "backend_pytest",
                "parsed": SimpleNamespace(
                    failed_tests=[
                        "backend/tests/test_auth.py::test_signup",
                        "backend/tests/test_auth.py::test_signup",
                    ],
                    error_details={"backend/tests/test_auth.py": "file-level failure"},
                ),
            },
            {
                "index": 1,
                "project_name": "Admin",
                "suite": "root_pytest",
                "parsed": SimpleNamespace(
                    failed_tests=["tests/test_admin.py::test_ok"],
                    error_details={"tests/test_admin.py::test_ok": "direct failure"},
                ),
            },
        ]

        self.assertEqual(
            collect_failed_tests(outcomes, project_name="Main"),
            [("Backend (pytest)", "backend/tests/test_auth.py::test_signup", "file-level failure")],
        )

    def test_collect_failed_test_manifest_entries_sanitizes_frontend_failed_files(self) -> None:
        outcomes = [
            {
                "index": 1,
                "project_name": "Main",
                "suite": "frontend_package_test",
                "failed_only": True,
                "parsed": SimpleNamespace(
                    failed_tests=["frontend/src/App.test.tsx", "frontend/src/App.test.tsx"],
                ),
            }
        ]

        self.assertEqual(
            collect_failed_test_manifest_entries(outcomes, project_name="Main"),
            [
                {
                    "suite": "Frontend (package test, failed only)",
                    "source": "frontend_package_test",
                    "failed_tests": ["frontend/src/App.test.tsx", "frontend/src/App.test.tsx"],
                    "failed_files": ["frontend/src/App.test.tsx"],
                    "invalid_failed_tests": 0,
                }
            ],
        )

    def test_collect_generic_and_context_failures_split_unparsed_from_parsed_failures(self) -> None:
        outcomes = [
            {
                "index": 1,
                "project_name": "Main",
                "suite": "configured",
                "returncode": 1,
                "failure_summary": "command failed before parsing",
                "parsed": SimpleNamespace(failed_tests=[]),
            },
            {
                "index": 2,
                "project_name": "Main",
                "suite": "backend_pytest",
                "returncode": 1,
                "failure_details": "captured traceback context",
                "parsed": SimpleNamespace(failed_tests=["backend/tests/test_auth.py::test_signup"]),
            },
        ]

        self.assertEqual(
            collect_generic_suite_failures(outcomes, project_name="Main"),
            [("Test command", "command failed before parsing")],
        )
        self.assertEqual(
            collect_suite_failure_contexts(outcomes, project_name="Main"),
            [("Backend (pytest)", "captured traceback context")],
        )

    def test_resolve_failed_test_error_and_suite_display_name_contracts(self) -> None:
        self.assertEqual(
            resolve_failed_test_error({"tests/test_app.py": "file failure"}, "tests/test_app.py::test_case"),
            "file failure",
        )
        self.assertEqual(suite_display_name("root_unittest", failed_only=True), "Repository tests (unittest, failed only)")
        self.assertEqual(suite_display_name("custom_suite"), "custom suite")

    def test_git_state_components_returns_hash_and_status_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            (repo / ".git").mkdir()
            head, status_hash, status_lines = git_state_components(repo)

        self.assertIsInstance(head, str)
        self.assertRegex(status_hash, r"^[0-9a-f]{40}$")
        self.assertIsInstance(status_lines, int)


if __name__ == "__main__":
    unittest.main()
