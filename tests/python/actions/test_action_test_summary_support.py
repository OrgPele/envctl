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
    new_test_results_run_dir,
    render_test_suite_overview,
    resolve_failed_test_error,
    short_failed_summary_path,
    suite_display_name,
    write_failed_tests_summary,
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

    def test_write_failed_tests_summary_persists_summary_state_manifest_and_shortcut(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run_dir = root / "runs" / "run-id" / "test-results" / "run_20260521_120000"
            project_root = root / "project"
            project_root.mkdir(parents=True)
            run_dir.mkdir(parents=True)

            outcome = {
                "index": 1,
                "project_name": "Main",
                "suite": "backend_pytest",
                "returncode": 1,
                "parsed": SimpleNamespace(
                    failed_tests=["tests/test_app.py::test_case"],
                    error_details={"tests/test_app.py": "assert False"},
                ),
            }

            summary = write_failed_tests_summary(
                run_dir=run_dir,
                project_name="Main",
                project_root=project_root,
                outcomes=[outcome],
                format_summary_error_lines=lambda text: [text],
            )

            summary_path = Path(str(summary["summary_path"]))
            short_summary_path = Path(str(summary["short_summary_path"]))
            manifest_path = Path(str(summary["manifest_path"]))
            state_path = Path(str(summary["state_path"]))

            self.assertTrue(summary_path.exists())
            self.assertEqual(short_summary_path, short_failed_summary_path(run_dir=run_dir, project_name="Main"))
            self.assertEqual(summary_path.read_text(encoding="utf-8"), short_summary_path.read_text(encoding="utf-8"))
            self.assertIn("[Backend (pytest)]", summary_path.read_text(encoding="utf-8"))
            self.assertIn("assert False", summary_path.read_text(encoding="utf-8"))
            self.assertIn("state|Main|", state_path.read_text(encoding="utf-8"))
            self.assertIn('"source": "backend_pytest"', manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "failed")
            self.assertEqual(summary["failed_tests"], 1)

    def test_new_test_results_run_dir_suffixes_existing_run_directory(self) -> None:
        class StateRepository:
            def __init__(self, root: Path) -> None:
                self.root = root

            def test_results_dir_path(self, run_id: str) -> Path:
                return self.root / run_id / "test-results"

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = StateRepository(Path(tmpdir))
            first = new_test_results_run_dir(repo, "run-id", now=lambda: "run_20260521_120000")
            second = new_test_results_run_dir(repo, "run-id", now=lambda: "run_20260521_120000")

        self.assertEqual(first.name, "run_20260521_120000")
        self.assertEqual(second.name, "run_20260521_120000_1")

    def test_render_test_suite_overview_groups_projects_and_links_failure_summary(self) -> None:
        parsed = SimpleNamespace(total=2, counts_detected=True, passed=1, failed=1, skipped=0)
        lines = render_test_suite_overview(
            [
                {
                    "index": 2,
                    "project_name": "Beta",
                    "suite": "configured",
                    "returncode": 0,
                    "duration_ms": 2000.0,
                    "parsed": parsed,
                },
                {
                    "index": 1,
                    "project_name": "Alpha",
                    "suite": "backend_pytest",
                    "returncode": 1,
                    "duration_ms": 1000.0,
                    "parsed": parsed,
                },
            ],
            colorize=lambda text, **_: text,
            summary_metadata={"Alpha": {"status": "failed", "short_summary_path": "/tmp/ft.txt"}},
            render_summary_path=lambda path: f"rendered:{path}",
        )

        self.assertEqual(lines[0], "")
        self.assertIn("Test Suite Summary", lines[2])
        self.assertLess(lines.index("Alpha"), lines.index("Beta"))
        self.assertIn("  rendered:/tmp/ft.txt", lines)
        self.assertTrue(any(line.startswith("Overall:") for line in lines))


if __name__ == "__main__":
    unittest.main()
