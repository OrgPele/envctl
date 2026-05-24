from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from envctl_engine.actions.action_failed_rerun_support import (
    build_failed_test_execution_specs_from_state,
    summary_indicates_extraction_failure,
)
from envctl_engine.actions.action_test_support import TestTargetContext as TargetContext


def _write_manifest(path: Path, *, failed_tests: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T00:00:00+00:00",
                "git_state": {"head": "abc", "status_hash": "hash", "status_lines": 0},
                "entries": [
                    {
                        "source": "backend_pytest",
                        "suite": "Backend (pytest)",
                        "failed_tests": failed_tests,
                        "failed_files": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class ActionFailedRerunSupportTests(unittest.TestCase):
    def test_missing_state_reports_full_suite_first(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Run the full test suite first"):
            build_failed_test_execution_specs_from_state(
                state=None,
                target_contexts=[],
                repo_root=Path("/repo"),
                shared_raw_command=None,
                backend_raw_command=None,
                frontend_raw_command=None,
                emit_status=lambda _message: None,
            )

    def test_invalid_saved_pytest_selectors_are_reported_and_valid_selectors_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            project = repo / "trees" / "feature-a" / "1"
            python_bin = project / "backend" / ".venv" / "bin" / "python"
            python_bin.parent.mkdir(parents=True, exist_ok=True)
            python_bin.write_text("", encoding="utf-8")
            manifest_path = Path(tmpdir) / "failed_tests_manifest.json"
            _write_manifest(
                manifest_path,
                failed_tests=["tests/test_api.py::test_good", "not a pytest node id"],
            )
            state = SimpleNamespace(
                metadata={
                    "project_test_summaries": {
                        "feature-a-1": {
                            "status": "failed",
                            "manifest_path": str(manifest_path),
                        }
                    }
                }
            )
            statuses: list[str] = []
            stdout = StringIO()

            with redirect_stdout(stdout):
                specs = build_failed_test_execution_specs_from_state(
                    state=state,
                    target_contexts=[
                        TargetContext(project_name="feature-a-1", project_root=project, target_obj=None)
                    ],
                    repo_root=repo,
                    shared_raw_command=None,
                    backend_raw_command=None,
                    frontend_raw_command=None,
                    emit_status=statuses.append,
                )

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].spec.command[-1], "tests/test_api.py::test_good")
        self.assertIn("Skipping 1 invalid saved pytest selector for feature-a-1", stdout.getvalue())
        self.assertEqual(statuses, ["Skipping 1 invalid saved pytest selector for feature-a-1; rerunning the remaining failed tests."])

    def test_extraction_failure_message_avoids_full_suite_instruction(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = Path(tmpdir) / "summary.txt"
            summary.write_text("- suite failed before envctl could extract failed tests\n", encoding="utf-8")
            state = SimpleNamespace(
                metadata={
                    "project_test_summaries": {
                        "Main": {
                            "status": "failed",
                            "short_summary_path": str(summary),
                        }
                    }
                }
            )
            stdout = StringIO()

            with self.assertRaisesRegex(RuntimeError, "failed before envctl could derive rerunnable test selectors"):
                with redirect_stdout(stdout):
                    build_failed_test_execution_specs_from_state(
                        state=state,
                        target_contexts=[TargetContext(project_name="Main", project_root=Path(tmpdir), target_obj=None)],
                        repo_root=Path(tmpdir),
                        shared_raw_command=None,
                        backend_raw_command=None,
                        frontend_raw_command=None,
                        emit_status=lambda _message: None,
                    )

            self.assertIn("No rerunnable failed tests were extracted for: Main", stdout.getvalue())
            self.assertTrue(summary_indicates_extraction_failure({"short_summary_path": str(summary)}))


if __name__ == "__main__":
    unittest.main()
