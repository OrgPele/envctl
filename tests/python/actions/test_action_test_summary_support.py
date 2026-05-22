from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from envctl_engine.actions.action_test_summary_support import (
    collect_failed_test_manifest_entries,
    collect_failed_tests,
    print_test_suite_overview,
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

    def test_print_test_suite_overview_groups_projects_and_renders_summary_link(self) -> None:
        outcomes = [
            {
                "index": 2,
                "project_name": "Web",
                "suite": "frontend_package_test",
                "returncode": 1,
                "duration_ms": 1500,
                "parsed": SimpleNamespace(
                    counts_detected=True,
                    total=3,
                    passed=1,
                    failed=1,
                    skipped=1,
                ),
            },
            {
                "index": 1,
                "project_name": "Api",
                "suite": "backend_pytest",
                "returncode": 0,
                "duration_ms": 500,
                "parsed": SimpleNamespace(
                    counts_detected=True,
                    total=2,
                    passed=2,
                    failed=0,
                    skipped=0,
                ),
            },
        ]

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            print_test_suite_overview(
                outcomes,
                summary_metadata={"Web": {"status": "failed", "short_summary_path": "/tmp/ft_web.txt"}},
                env={"ENVCTL_UI_HYPERLINK_MODE": "off"},
                colorize=lambda text, **_kwargs: text,
            )

        rendered = output.getvalue()
        self.assertIn("Test Suite Summary", rendered)
        self.assertLess(rendered.index("Api"), rendered.index("Web"))
        self.assertIn("Backend (pytest): 2 passed, 0 failed, 0 skipped", rendered)
        self.assertIn("Frontend (package test): 1 passed, 1 failed, 1 skipped", rendered)
        self.assertIn("failure summary:", rendered)
        self.assertIn("/tmp/ft_web.txt", rendered)
        self.assertIn("Overall: 3 passed, 1 failed, 1 skipped", rendered)


if __name__ == "__main__":
    unittest.main()
