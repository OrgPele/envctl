from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from envctl_engine.actions.action_test_summary_support import (
    collect_failed_test_manifest_entries,
    collect_failed_tests,
    suite_display_name,
    write_failed_tests_summary,
)


class ActionTestSummarySupportTests(unittest.TestCase):
    def test_collect_failed_tests_deduplicates_and_resolves_file_level_errors(self) -> None:
        outcomes = [
            {
                "index": 2,
                "project_name": "Main",
                "suite": "backend_pytest",
                "parsed": SimpleNamespace(
                    failed_tests=["tests/test_auth.py::test_signup", "tests/test_auth.py::test_signup"],
                    error_details={"tests/test_auth.py": "file level failure"},
                ),
            },
            {
                "index": 1,
                "project_name": "Other",
                "suite": "root_pytest",
                "parsed": SimpleNamespace(failed_tests=["tests/test_other.py::test_case"], error_details={}),
            },
        ]

        self.assertEqual(
            collect_failed_tests(outcomes, project_name="Main"),
            [("Backend (pytest)", "tests/test_auth.py::test_signup", "file level failure")],
        )

    def test_collect_failed_test_manifest_entries_sanitizes_frontend_failed_files(self) -> None:
        outcomes = [
            {
                "index": 1,
                "project_name": "Main",
                "suite": "frontend_package_test",
                "parsed": SimpleNamespace(
                    failed_tests=["frontend/src/App.test.tsx::renders", "bad selector with spaces"],
                ),
            }
        ]

        entries = collect_failed_test_manifest_entries(outcomes, project_name="Main")

        self.assertEqual(entries[0]["suite"], "Frontend (package test)")
        self.assertEqual(entries[0]["source"], "frontend_package_test")
        self.assertIn("frontend/src/App.test.tsx::renders", entries[0]["failed_tests"])
        self.assertIn("frontend/src/App.test.tsx", entries[0]["failed_files"])
        self.assertEqual(entries[0]["invalid_failed_tests"], 0)

    def test_write_failed_tests_summary_writes_summary_manifest_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "run"
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir()
            outcomes = [
                {
                    "index": 1,
                    "project_name": "Main",
                    "project_root": str(project_root),
                    "suite": "backend_pytest",
                    "returncode": 1,
                    "parsed": SimpleNamespace(
                        failed_tests=["tests/test_auth.py::test_signup"],
                        error_details={"tests/test_auth.py::test_signup": "AssertionError: boom"},
                    ),
                }
            ]

            result = write_failed_tests_summary(
                run_dir=run_dir,
                project_name="Main",
                project_root=project_root,
                outcomes=outcomes,
                short_failed_summary_path=lambda **_kwargs: run_dir / "ft_main.txt",
                format_summary_error_lines=lambda text: [line.strip() for line in text.splitlines() if line.strip()],
                git_state_components=lambda _root: ("HEAD", "hash", 2),
            )

            summary_path = Path(str(result["summary_path"]))
            manifest_path = Path(str(result["manifest_path"]))
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["failed_tests"], 1)
            self.assertEqual(result["failed_manifest_entries"], 1)
            self.assertIn("tests/test_auth.py::test_signup", summary_path.read_text(encoding="utf-8"))
            self.assertIn("AssertionError: boom", summary_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["git_state"], {"head": "HEAD", "status_hash": "hash", "status_lines": 2})

    def test_suite_display_name_keeps_failed_only_suffix(self) -> None:
        self.assertEqual(suite_display_name("backend_pytest", failed_only=True), "Backend (pytest, failed only)")


if __name__ == "__main__":
    unittest.main()
