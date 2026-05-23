from __future__ import annotations

import importlib
import json
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.python.actions.actions_parity_test_support import (
    ActionCommandOrchestrator,
    PythonEngineRuntime,
    RunState,
    ServiceRecord,
    _ActionsParityTestCase,
    _FakeRunner,
    action_test_summary_support_module,
    collect_failed_test_manifest_entries,
    default_git_state_components,
    engine_runtime_module,
    parse_route,
)


class ActionsTestSummaryParityTests(_ActionsParityTestCase):
    def test_test_action_writes_failed_tests_summary_and_persists_dashboard_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 1'", "NO_COLOR": "1"},
            )
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            state = RunState(
                run_id="run-tests-artifact",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree_root),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "feature-a-1 Frontend": ServiceRecord(
                        name="feature-a-1 Frontend",
                        type="frontend",
                        cwd=str(tree_root),
                        pid=2222,
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
            )
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            class _FailingRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = None

                def run_tests(self, _command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    from envctl_engine.test_output.parser_base import TestResult

                    self.last_result = TestResult(
                        passed=10,
                        failed=1,
                        skipped=0,
                        total=11,
                        failed_tests=["backend/tests/test_auth.py::test_signup_regression"],
                        error_details={
                            "backend/tests/test_auth.py::test_signup_regression": (
                                "\x1b]22;default\x07"
                                "AssertionError: expected 201, got 500\n"
                                "\x1b[15;72H"
                                "\\x1b[48;2;39;39;39m \x1b[0m"
                            )
                        },
                    )
                    return SimpleNamespace(returncode=1, stdout="", stderr="suite failed")

            dispatch_out = StringIO()
            with (
                redirect_stdout(dispatch_out),
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _FailingRunner),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 1)

            refreshed = engine._try_load_existing_state(mode="trees", strict_mode_match=False)
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            summaries = refreshed.metadata.get("project_test_summaries")
            self.assertIsInstance(summaries, dict)
            assert isinstance(summaries, dict)
            project_entry = summaries.get("feature-a-1")
            self.assertIsInstance(project_entry, dict)
            assert isinstance(project_entry, dict)
            summary_path = project_entry.get("summary_path")
            short_summary_path = project_entry.get("short_summary_path")
            manifest_path = project_entry.get("manifest_path")
            self.assertIsInstance(summary_path, str)
            assert isinstance(summary_path, str)
            self.assertIsInstance(short_summary_path, str)
            assert isinstance(short_summary_path, str)
            self.assertIsInstance(manifest_path, str)
            assert isinstance(manifest_path, str)
            expected_root = engine.runtime_root / "runs" / state.run_id / "test-results"
            self.assertTrue(summary_path.endswith("failed_tests_summary.txt"))
            self.assertRegex(Path(short_summary_path).name, r"^ft_[0-9a-f]{10}\.txt$")
            self.assertTrue(manifest_path.endswith("failed_tests_manifest.json"))
            self.assertTrue(Path(summary_path).is_file())
            self.assertTrue(Path(short_summary_path).is_file())
            self.assertTrue(Path(manifest_path).is_file())
            self.assertTrue(Path(summary_path).is_relative_to(expected_root))
            self.assertTrue(Path(short_summary_path).is_relative_to(engine.runtime_root / "runs" / state.run_id))
            self.assertTrue(Path(manifest_path).is_relative_to(expected_root))
            summary_text = Path(summary_path).read_text(encoding="utf-8")
            self.assertEqual(summary_text, Path(short_summary_path).read_text(encoding="utf-8"))
            manifest_payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            self.assertIn("backend/tests/test_auth.py::test_signup_regression", summary_text)
            self.assertIn("AssertionError: expected 201, got 500", summary_text)
            self.assertNotIn("\x1b", summary_text)
            self.assertNotIn("\\x1b", summary_text)
            self.assertNotIn("48;2;39;39;39m", summary_text)
            self.assertEqual(
                manifest_payload["entries"][0]["failed_tests"],
                ["backend/tests/test_auth.py::test_signup_regression"],
            )
            self.assertEqual(project_entry.get("status"), "failed")
            self.assertEqual(
                project_entry.get("summary_excerpt"),
                [
                    "[Test command]",
                    "backend/tests/test_auth.py::test_signup_regression",
                    "AssertionError: expected 201, got 500",
                ],
            )
            results_root = refreshed.metadata.get("project_test_results_root")
            self.assertEqual(results_root, str(Path(summary_path).parent.parent))
            self.assertTrue(Path(str(results_root)).is_relative_to(expected_root))
            self.assertFalse((repo / "test-results").exists())
            dispatch_rendered = dispatch_out.getvalue()
            self.assertIn("failure summary:", dispatch_rendered)
            self.assertIn(short_summary_path, dispatch_rendered)
            self.assertNotIn("backend/tests/test_auth.py::test_signup_regression", dispatch_rendered)
            self.assertNotIn("AssertionError: expected 201, got 500", dispatch_rendered)

            dashboard_out = StringIO()
            with redirect_stdout(dashboard_out):
                engine._print_dashboard_snapshot(refreshed)
            rendered = dashboard_out.getvalue()
            self.assertIn("tests:", rendered)
            self.assertIn("backend/tests/test_auth.py::test_signup_regression", rendered)
            self.assertIn("AssertionError: expected 201, got 500", rendered)
            self.assertIn(short_summary_path, rendered)
            self.assertNotIn(summary_path, rendered)

    def test_failed_test_manifest_filters_invalid_pytest_error_lines(self) -> None:
        parser = importlib.import_module("envctl_engine.test_output.parser_pytest").PytestOutputParser()
        parsed = parser.parse_output(
            "\n".join(
                [
                    "ERROR: file or directory not found: app.core.middleware:logging_helpers.py:113 Unhandled request error",
                    "ERROR backend/tests/unit/test_repositories/test_faq_repo.py::test_faq_repo - AssertionError: boom",
                    "========================= 1 error in 0.12s =========================",
                ]
            )
        )
        entries = collect_failed_test_manifest_entries(
            [
                {
                    "index": 0,
                    "project_name": "Main",
                    "suite": "backend_pytest",
                    "parsed": parsed,
                }
            ],
            project_name="Main",
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(
            entries[0]["failed_tests"],
            ["backend/tests/unit/test_repositories/test_faq_repo.py::test_faq_repo"],
        )

    def test_failed_only_summary_persistence_preserves_previous_manifest_after_extraction_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})
            state = RunState(
                run_id="run-preserve-failed-only",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )
            head, status_hash, status_lines = default_git_state_components(repo)
            previous_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260312_100000" / "Main"
            previous_dir.mkdir(parents=True, exist_ok=True)
            previous_manifest_path = previous_dir / "failed_tests_manifest.json"
            previous_manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-12T10:00:00+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": head,
                            "status_hash": status_hash,
                            "status_lines": status_lines,
                        },
                        "entries": [
                            {
                                "suite": "Backend (pytest)",
                                "source": "backend_pytest",
                                "failed_tests": ["backend/tests/test_auth.py::test_signup_regression"],
                                "failed_files": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            previous_summary_path = previous_dir / "failed_tests_summary.txt"
            previous_summary_path.write_text("previous summary", encoding="utf-8")
            previous_short_summary_path = engine.runtime_root / "runs" / state.run_id / "ft_preserved.txt"
            previous_short_summary_path.write_text("previous summary", encoding="utf-8")
            state.metadata["project_test_summaries"] = {
                "Main": {
                    "summary_path": str(previous_summary_path),
                    "short_summary_path": str(previous_short_summary_path),
                    "manifest_path": str(previous_manifest_path),
                    "failed_tests": 1,
                    "failed_manifest_entries": 1,
                    "status": "failed",
                }
            }
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            orchestrator = ActionCommandOrchestrator(engine)
            route = parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"})
            outcomes = [
                {
                    "index": 1,
                    "project_name": "Main",
                    "project_root": str(repo),
                    "suite": "backend_pytest",
                    "failed_only": True,
                    "returncode": 1,
                    "parsed": SimpleNamespace(failed_tests=[], error_details={}),
                    "failure_summary": "ERROR: file or directory not found: poisoned selector",
                }
            ]

            summaries = orchestrator._persist_test_summary_artifacts(
                route=route,
                targets=[SimpleNamespace(name="Main", root=str(repo))],
                outcomes=outcomes,
            )

            project_entry = summaries["Main"]
            self.assertEqual(project_entry["manifest_path"], str(previous_manifest_path))
            self.assertEqual(project_entry["short_summary_path"], str(previous_short_summary_path))
            self.assertTrue(bool(project_entry.get("preserved_after_failed_only_extraction_failure")))

    def test_failed_test_summary_omits_terminal_chrome_and_separator_noise(self) -> None:
        lines = action_test_summary_support_module.format_summary_error_lines(
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

    def test_failed_test_summary_keeps_relevant_traceback_tail(self) -> None:
        lines = action_test_summary_support_module.format_summary_error_lines(
            "\n".join(
                [
                    "Traceback (most recent call last):",
                    'File "/opt/homebrew/Cellar/python@3.12/.../asyncio/runners.py", line 118, in run',
                    "return self._loop.run_until_complete(task)",
                    'File "/opt/homebrew/Cellar/python@3.12/.../asyncio/base_events.py", line 691, in run_until_complete',
                    "return future.result()",
                    'File "/Users/kfiramar/projects/envctl/tests/python/ui/test_textual_selector_responsiveness.py", line 274, in test_mouse_click_selects_single_mode_without_enter',
                    'self.assertEqual(app.return_value, ["beta"])',
                    "AssertionError: None != ['beta']",
                ]
            )
        )
        rendered = "\n".join(lines)
        self.assertIn("Traceback (most recent call last):", rendered)
        self.assertIn('File "/opt/homebrew/Cellar/python@3.12/.../asyncio/runners.py", line 118, in run', rendered)
        self.assertIn(
            'File "/Users/kfiramar/projects/envctl/tests/python/ui/test_textual_selector_responsiveness.py", line 274, in test_mouse_click_selects_single_mode_without_enter',
            rendered,
        )
        self.assertIn('self.assertEqual(app.return_value, ["beta"])', rendered)
        self.assertIn("AssertionError: None != ['beta']", rendered)

    def test_failed_test_summary_keeps_captured_output_sections(self) -> None:
        lines = action_test_summary_support_module.format_summary_error_lines(
            "\n".join(
                [
                    "Traceback (most recent call last):",
                    'File "/Users/kfiramar/projects/envctl/tests/python/ui/test_textual_selector_responsiveness.py", line 274, in test_mouse_click_selects_single_mode_without_enter',
                    'self.assertEqual(app.return_value, ["beta"])',
                    "AssertionError: None != ['beta']",
                    "Captured stdout call",
                    "selector state before click: focused=selector-row-1",
                    "return_value=None",
                    "Captured stderr call",
                    "mouse event propagated",
                ]
            )
        )
        rendered = "\n".join(lines)
        self.assertIn("Captured stdout call", rendered)
        self.assertIn("selector state before click: focused=selector-row-1", rendered)
        self.assertIn("Captured stderr call", rendered)
        self.assertIn("mouse event propagated", rendered)

    def test_failed_test_summary_keeps_multiline_exception_body(self) -> None:
        lines = action_test_summary_support_module.format_summary_error_lines(
            "\n".join(
                [
                    "Traceback (most recent call last):",
                    'File "/Users/kfiramar/projects/envctl/python/foo.py", line 10, in explode',
                    "raise RuntimeError('bad state')",
                    "RuntimeError: invalid selector state",
                    "details: selected_row=None",
                    "details: expected token=beta",
                ]
            )
        )
        rendered = "\n".join(lines)
        self.assertIn("RuntimeError: invalid selector state", rendered)
        self.assertIn("details: selected_row=None", rendered)
        self.assertIn("details: expected token=beta", rendered)

    def test_failed_test_summary_keeps_multiple_user_frames_and_exception_context(self) -> None:
        lines = action_test_summary_support_module.format_summary_error_lines(
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
                ]
            )
        )
        rendered = "\n".join(lines)
        self.assertIn(
            'File "/Users/kfiramar/projects/envctl/python/envctl_engine/ui/foo.py", line 10, in helper', rendered
        )
        self.assertIn(
            'File "/Users/kfiramar/projects/envctl/tests/python/ui/test_textual_selector_responsiveness.py", line 274, in test_mouse_click_selects_single_mode_without_enter',
            rendered,
        )
        self.assertIn("During handling of the above exception, another exception occurred:", rendered)
        self.assertIn("RuntimeError: wrapper failed", rendered)

    def test_test_action_writes_passed_summary_with_no_failed_tests_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 0'"},
            )

            state = RunState(
                run_id="run-tests-artifact-pass",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree_root),
                        pid=3333,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "feature-a-1 Frontend": ServiceRecord(
                        name="feature-a-1 Frontend",
                        type="frontend",
                        cwd=str(tree_root),
                        pid=4444,
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
            )
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            class _PassingRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = None

                def run_tests(self, _command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    from envctl_engine.test_output.parser_base import TestResult

                    self.last_result = TestResult(
                        passed=5,
                        failed=0,
                        skipped=1,
                        total=6,
                        failed_tests=[],
                        error_details={},
                    )
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            refreshed = engine._try_load_existing_state(mode="trees", strict_mode_match=False)
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            summaries = refreshed.metadata.get("project_test_summaries")
            self.assertIsInstance(summaries, dict)
            assert isinstance(summaries, dict)
            project_entry = summaries.get("feature-a-1")
            self.assertIsInstance(project_entry, dict)
            assert isinstance(project_entry, dict)
            summary_path = project_entry.get("summary_path")
            short_summary_path = project_entry.get("short_summary_path")
            self.assertIsInstance(summary_path, str)
            assert isinstance(summary_path, str)
            self.assertIsInstance(short_summary_path, str)
            assert isinstance(short_summary_path, str)
            expected_root = engine.runtime_root / "runs" / state.run_id / "test-results"
            self.assertTrue(Path(summary_path).is_relative_to(expected_root))
            self.assertTrue(Path(short_summary_path).is_relative_to(engine.runtime_root / "runs" / state.run_id))
            text = Path(summary_path).read_text(encoding="utf-8")
            self.assertIn("No failed tests.", text)
            self.assertEqual(text, Path(short_summary_path).read_text(encoding="utf-8"))
            self.assertEqual(project_entry.get("status"), "passed")
            self.assertEqual(
                refreshed.metadata.get("project_test_results_root"),
                str(Path(summary_path).parent.parent),
            )
            self.assertFalse((repo / "test-results").exists())

    def test_failed_test_summary_artifacts_are_scoped_per_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            for tree in (tree_a, tree_b):
                (tree / "backend" / "tests").mkdir(parents=True, exist_ok=True)
                (tree / "backend" / "pyproject.toml").write_text(
                    "[project]\nname='backend'\nversion='1.0.0'\n",
                    encoding="utf-8",
                )

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})
            state = RunState(
                run_id="run-tests-artifact-multi",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree_a),
                        pid=1001,
                        requested_port=8001,
                        actual_port=8001,
                        status="running",
                    ),
                    "feature-b-1 Backend": ServiceRecord(
                        name="feature-b-1 Backend",
                        type="backend",
                        cwd=str(tree_b),
                        pid=1002,
                        requested_port=8002,
                        actual_port=8002,
                        status="running",
                    ),
                },
            )
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            class _PerProjectFailingRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = None

                def run_tests(self, _command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    from envctl_engine.test_output.parser_base import TestResult

                    cwd_text = str(cwd or "")
                    marker = "feature-a-1" if "feature-a" in cwd_text else "feature-b-1"
                    self.last_result = TestResult(
                        passed=2,
                        failed=1,
                        skipped=0,
                        total=3,
                        failed_tests=[f"{marker}/backend/tests/test_auth.py::test_signup"],
                        error_details={
                            f"{marker}/backend/tests/test_auth.py::test_signup": f"AssertionError: {marker} failed"
                        },
                    )
                    return SimpleNamespace(returncode=1, stdout="", stderr=f"{marker} suite failed")

            with (
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PerProjectFailingRunner),
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
            ):
                route = parse_route(["test", "--all", "frontend=false"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                rendered_out = StringIO()
                with redirect_stdout(rendered_out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 1)
            refreshed = engine._try_load_existing_state(mode="trees", strict_mode_match=False)
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            summaries = refreshed.metadata.get("project_test_summaries")
            self.assertIsInstance(summaries, dict)
            assert isinstance(summaries, dict)

            first = summaries.get("feature-a-1")
            second = summaries.get("feature-b-1")
            self.assertIsInstance(first, dict)
            self.assertIsInstance(second, dict)
            assert isinstance(first, dict)
            assert isinstance(second, dict)

            first_text = Path(str(first.get("summary_path"))).read_text(encoding="utf-8")
            second_text = Path(str(second.get("summary_path"))).read_text(encoding="utf-8")
            self.assertIn("feature-a-1/backend/tests/test_auth.py::test_signup", first_text)
            self.assertNotIn("feature-b-1/backend/tests/test_auth.py::test_signup", first_text)
            self.assertIn("feature-b-1/backend/tests/test_auth.py::test_signup", second_text)
            self.assertNotIn("feature-a-1/backend/tests/test_auth.py::test_signup", second_text)
            rendered = rendered_out.getvalue()
            first_short = str(first.get("short_summary_path"))
            second_short = str(second.get("short_summary_path"))
            self.assertIn("feature-a-1", rendered)
            self.assertIn(first_short, rendered)
            self.assertIn("feature-b-1", rendered)
            self.assertIn(second_short, rendered)

