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
    format_summary_error_lines,
    persist_test_summary_artifacts,
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

    def test_persist_test_summary_artifacts_updates_state_metadata_and_emits_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run_dir = root / "runtime" / "runs" / "run-1" / "test-results" / "run-current"
            saved: list[object] = []
            events: list[tuple[str, dict[str, object]]] = []
            state = SimpleNamespace(
                run_id="run-1",
                metadata={"project_test_summaries": {"Other": {"status": "passed"}}},
            )
            runtime = SimpleNamespace(
                load_existing_state=lambda mode: state if mode == "main" else None,
                state_repository=SimpleNamespace(save_resume_state=lambda **kwargs: saved.append(kwargs["state"])),
                emit=lambda event, **payload: events.append((event, payload)),
            )
            route = SimpleNamespace(mode="main")
            target = SimpleNamespace(name="Main", root=str(root / "repo"))

            summaries = persist_test_summary_artifacts(
                runtime=runtime,
                route=route,
                targets=[target],
                outcomes=[{"project_name": "Main", "project_root": str(root / "repo"), "returncode": 0}],
                new_test_results_run_dir=lambda _runtime, run_id: run_dir,
                write_failed_tests_summary_fn=lambda **kwargs: {
                    "status": "passed",
                    "run_dir": str(kwargs["run_dir"]),
                    "previous": kwargs["previous_entry"],
                },
                runtime_map_builder=lambda *_args, **_kwargs: {},
            )

            self.assertEqual(summaries["Main"]["status"], "passed")
            self.assertEqual(summaries["Main"]["previous"], None)
            self.assertEqual(state.metadata["project_test_summaries"]["Other"]["status"], "passed")
            self.assertEqual(state.metadata["project_test_summaries"]["Main"]["run_dir"], str(run_dir))
            self.assertEqual(state.metadata["project_test_results_root"], str(run_dir))
            self.assertIn("project_test_results_updated_at", state.metadata)
            self.assertEqual(saved, [state])
            self.assertEqual(
                events,
                [("test.summary.persisted", {"mode": "main", "projects": ["Main"], "run_dir": str(run_dir)})],
            )

    def test_suite_display_name_keeps_failed_only_suffix(self) -> None:
        self.assertEqual(suite_display_name("backend_pytest", failed_only=True), "Backend (pytest, failed only)")

    def test_format_summary_error_lines_omits_terminal_chrome_and_keeps_failure(self) -> None:
        lines = format_summary_error_lines(
            "\n".join(
                [
                    "----------------------------------------------------------------------",
                    "Traceback (most recent call last):",
                    'AssertionError: Regex didn\'t match: something not found in "\\x1b[48;2;39;39;39m..."',
                    "  ╭────────────────────────────────────────────────────╮",
                    "  │  Run tests for                                    │",
                    "RESULT_SERVICES=Main Admin",
                    'File "/tmp/test.py", line 10, in test_case',
                ]
            )
        )

        rendered = "\n".join(lines)
        self.assertIn("Traceback (most recent call last):", rendered)
        self.assertIn("AssertionError: Regex didn't match: something not found in <omitted output>", rendered)
        self.assertIn('File "/tmp/test.py", line 10, in test_case', rendered)
        self.assertNotIn("------", rendered)
        self.assertNotIn("Run tests for", rendered)
        self.assertNotIn("RESULT_SERVICES=", rendered)

    def test_format_summary_error_lines_preserves_structured_traceback_context(self) -> None:
        lines = format_summary_error_lines(
            "\n".join(
                [
                    "Traceback (most recent call last):",
                    'File "/Users/kfiramar/projects/envctl/python/envctl_engine/ui/foo.py", line 10, in helper',
                    "do_the_thing()",
                    'File "/Users/kfiramar/projects/envctl/tests/python/ui/test_textual_selector_responsiveness.py", line 274, in test_mouse_click_selects_single_mode_without_enter',
                    'self.assertEqual(app.return_value, ["beta"])',
                    "AssertionError: None != ['beta']",
                    "",
                    "During handling of the above exception, another exception occurred:",
                    "Traceback (most recent call last):",
                    'File "/Users/kfiramar/projects/envctl/python/envctl_engine/ui/bar.py", line 22, in wrapper',
                    "raise RuntimeError('wrapper failed')",
                    "RuntimeError: wrapper failed",
                    "Captured stdout call",
                    "selector state before click: focused=selector-row-1",
                ]
            )
        )

        rendered = "\n".join(lines)
        self.assertIn('File "/Users/kfiramar/projects/envctl/python/envctl_engine/ui/foo.py", line 10, in helper', rendered)
        self.assertIn(
            'File "/Users/kfiramar/projects/envctl/tests/python/ui/test_textual_selector_responsiveness.py", line 274, in test_mouse_click_selects_single_mode_without_enter',
            rendered,
        )
        self.assertIn("During handling of the above exception, another exception occurred:", rendered)
        self.assertIn("RuntimeError: wrapper failed", rendered)
        self.assertIn("Captured stdout call", rendered)
        self.assertIn("selector state before click: focused=selector-row-1", rendered)

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
