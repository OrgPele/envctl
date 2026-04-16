from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.shared.process_runner import ProcessRunner
from envctl_engine.test_output.test_runner import TestRunner


class _RunOnlyProcessRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
        _ = cwd, env, timeout
        self.calls.append(tuple(str(part) for part in cmd))
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            stdout="1 passed in 0.01s\n",
            stderr="",
        )


class _RuntimeStub:
    def __init__(self) -> None:
        self.process_runner = _RunOnlyProcessRunner()


class _RunStreamingLegacyRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run_streaming(self, cmd, *, cwd=None, env=None, timeout=None, callback=None):  # noqa: ANN001
        _ = cwd, env, timeout
        self.calls.append({"cmd": tuple(str(part) for part in cmd), "callback": callback})
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            stdout="1 passed in 0.01s\n",
            stderr="",
        )


class _RunStreamingModernRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run_streaming(
        self,
        cmd,
        *,
        cwd=None,
        env=None,
        timeout=None,
        callback=None,
        show_spinner=True,
        echo_output=True,
    ):  # noqa: ANN001
        _ = cwd, env, timeout
        self.calls.append(
            {
                "cmd": tuple(str(part) for part in cmd),
                "callback": callback,
                "show_spinner": show_spinner,
                "echo_output": echo_output,
            }
        )
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            stdout="1 passed in 0.01s\n",
            stderr="",
        )


class _RunStreamingWithStdinRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run_streaming(
        self,
        cmd,
        *,
        cwd=None,
        env=None,
        timeout=None,
        callback=None,
        show_spinner=True,
        echo_output=True,
        stdin=None,
    ):  # noqa: ANN001
        _ = cwd, env, timeout, callback, show_spinner, echo_output
        self.calls.append({"cmd": tuple(str(part) for part in cmd), "stdin": stdin})
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            stdout="1 passed in 0.01s\n",
            stderr="",
        )


class _RunStreamingProcessStartedRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run_streaming(
        self,
        cmd,
        *,
        cwd=None,
        env=None,
        timeout=None,
        callback=None,
        process_started_callback=None,
        show_spinner=True,
        echo_output=True,
        stdin=None,
    ):  # noqa: ANN001
        _ = cwd, env, timeout, callback, show_spinner, echo_output, stdin
        self.calls.append(
            {
                "cmd": tuple(str(part) for part in cmd),
                "process_started_callback": process_started_callback,
            }
        )
        if callable(process_started_callback):
            process_started_callback(2468)
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            stdout="1 passed in 0.01s\n",
            stderr="",
        )


class _RunOnlyProcessStartedRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, cmd, *, cwd=None, env=None, timeout=None, stdin=None, process_started_callback=None):  # noqa: ANN001
        _ = cwd, env, timeout, stdin
        self.calls.append(
            {
                "cmd": tuple(str(part) for part in cmd),
                "process_started_callback": process_started_callback,
            }
        )
        if callable(process_started_callback):
            process_started_callback(1357)
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            stdout="1 passed in 0.01s\n",
            stderr="",
        )


class _RunStreamingVitestRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run_streaming(
        self,
        cmd,
        *,
        cwd=None,
        env=None,
        timeout=None,
        callback=None,
        show_spinner=True,
        echo_output=True,
        stdin=None,
    ):  # noqa: ANN001
        _ = cwd, env, timeout, show_spinner, echo_output, stdin
        self.calls.append({"cmd": tuple(str(part) for part in cmd), "callback": callback})
        if callable(callback):
            callback("ENVCTL_TEST_DISCOVERED:47")
            callback("ENVCTL_TEST_COMPLETE:5")
            callback("ENVCTL_TEST_TOTAL:179")
            callback("ENVCTL_TEST_PROGRESS:6/179")
        return subprocess.CompletedProcess(
            args=list(cmd),
            returncode=0,
            stdout="Tests  179 passed (179)\n",
            stderr="",
        )


class _RuntimeStreamingStub:
    def __init__(self, process_runner) -> None:  # noqa: ANN001
        self.process_runner = process_runner


class _MalformedUtf8StreamingRunner:
    def run_streaming(
        self,
        cmd,
        *,
        cwd=None,
        env=None,
        timeout=None,
        callback=None,
        show_spinner=True,
        echo_output=True,
        stdin=None,
    ):  # noqa: ANN001
        _ = cmd, cwd, env, timeout, show_spinner, echo_output, stdin
        if callable(callback):
            callback("ENVCTL_TEST_TOTAL:2")
            callback("ENVCTL_TEST_PROGRESS:1/2")
            callback("bad byte: �")
            callback("ENVCTL_TEST_PROGRESS:2/2")
            callback("========================= 2 passed in 0.03s =========================")
        return subprocess.CompletedProcess(
            args=["python", "-m", "pytest"],
            returncode=0,
            stdout=(
                "ENVCTL_TEST_TOTAL:2\n"
                "ENVCTL_TEST_PROGRESS:1/2\n"
                "bad byte: �\n"
                "ENVCTL_TEST_PROGRESS:2/2\n"
                "========================= 2 passed in 0.03s =========================\n"
            ),
            stderr="",
        )


class TestRunnerStreamingFallbackTests(unittest.TestCase):
    def test_run_tests_tolerates_replaced_non_utf8_output_during_streaming(self) -> None:
        runtime = _RuntimeStreamingStub(_MalformedUtf8StreamingRunner())
        runner = TestRunner(runtime, verbose=False, render_output=False)
        progress_updates: list[tuple[int, int]] = []

        completed = runner.run_tests(
            ["python", "-m", "pytest"],
            progress_callback=lambda current, total: progress_updates.append((current, total)),
        )

        self.assertEqual(completed.returncode, 0)
        self.assertIn("bad byte: �", completed.stdout)
        self.assertEqual(progress_updates, [(0, 2), (1, 2), (2, 2)])
        assert runner.last_result is not None
        self.assertTrue(runner.last_result.counts_detected)
        self.assertEqual(runner.last_result.total, 2)
        self.assertEqual(runner.last_result.passed, 2)

    def test_run_tests_reports_live_unittest_progress_with_real_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            tests_dir = project_root / "tests"
            tests_dir.mkdir(parents=True, exist_ok=True)
            (tests_dir / "test_sample.py").write_text(
                "\n".join(
                    [
                        "import unittest",
                        "",
                        "class SampleTests(unittest.TestCase):",
                        "    def test_one(self):",
                        "        self.assertTrue(True)",
                        "",
                        "    def test_two(self):",
                        "        self.assertEqual(2, 2)",
                        "",
                        "    def test_three(self):",
                        "        self.assertIn('a', 'cat')",
                        "",
                        "if __name__ == '__main__':",
                        "    unittest.main()",
                    ]
                ),
                encoding="utf-8",
            )

            runtime = _RuntimeStreamingStub(ProcessRunner())
            runner = TestRunner(runtime, verbose=False, render_output=False)
            progress_updates: list[tuple[int, int]] = []

            completed = runner.run_tests(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
                cwd=project_root,
                progress_callback=lambda current, total: progress_updates.append((current, total)),
            )

            self.assertEqual(completed.returncode, 0)
            self.assertNotIn("ENVCTL_TEST_PROGRESS", completed.stdout)
            self.assertNotIn("ENVCTL_TEST_TOTAL", completed.stdout)
            self.assertIn((0, 3), progress_updates)
            self.assertIn((3, 3), progress_updates)
            assert runner.last_result is not None
            self.assertEqual(runner.last_result.total, 3)
            self.assertEqual(runner.last_result.passed, 3)

    def test_run_tests_reports_live_pytest_progress_with_real_subprocess(self) -> None:
        if importlib.util.find_spec("pytest") is None:
            self.skipTest("pytest is not installed in this interpreter")
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            tests_dir = project_root / "tests"
            tests_dir.mkdir(parents=True, exist_ok=True)
            (tests_dir / "test_sample.py").write_text(
                "\n".join(
                    [
                        "def test_one():",
                        "    assert True",
                        "",
                        "def test_two():",
                        "    assert 1 + 1 == 2",
                    ]
                ),
                encoding="utf-8",
            )

            runtime = _RuntimeStreamingStub(ProcessRunner())
            runner = TestRunner(runtime, verbose=False, render_output=False)
            progress_updates: list[tuple[int, int]] = []

            completed = runner.run_tests(
                [sys.executable, "-m", "pytest", "tests"],
                cwd=project_root,
                progress_callback=lambda current, total: progress_updates.append((current, total)),
            )

            self.assertEqual(completed.returncode, 0, msg=completed.stdout)
            self.assertNotIn("ENVCTL_TEST_PROGRESS", completed.stdout)
            self.assertNotIn("ENVCTL_TEST_TOTAL", completed.stdout)
            self.assertIn((0, 2), progress_updates)
            self.assertIn((2, 2), progress_updates)
            assert runner.last_result is not None
            self.assertTrue(runner.last_result.counts_detected)
            self.assertEqual(runner.last_result.total, 2)
            self.assertEqual(runner.last_result.passed, 2)

    def test_run_tests_parses_unittest_summary_counts(self) -> None:
        class _UnittestRunner:
            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cmd, cwd, env, timeout
                return subprocess.CompletedProcess(
                    args=["python", "-m", "unittest"],
                    returncode=0,
                    stdout="..\n----------------------------------------------------------------------\nRan 2 tests in 0.003s\n\nOK\n",
                    stderr="",
                )

        runtime = _RuntimeStreamingStub(_UnittestRunner())
        runner = TestRunner(runtime, verbose=False)

        completed = runner.run_tests(["python", "-m", "unittest", "discover"])

        self.assertEqual(completed.returncode, 0)
        assert runner.last_result is not None
        self.assertTrue(runner.last_result.counts_detected)
        self.assertEqual(runner.last_result.total, 2)
        self.assertEqual(runner.last_result.passed, 2)
        self.assertEqual(runner.last_result.failed, 0)

    def test_run_tests_falls_back_to_run_when_run_streaming_missing(self) -> None:
        runtime = _RuntimeStub()
        runner = TestRunner(runtime, verbose=False)

        completed = runner.run_tests(["python", "-m", "pytest"])

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(len(runtime.process_runner.calls), 1)
        self.assertIn(
            ("python", "-m", "pytest", "-p", "envctl_engine.test_output.pytest_progress_plugin"),
            runtime.process_runner.calls,
        )

    def test_run_tests_forwards_process_started_callback_to_run_streaming(self) -> None:
        process_runner = _RunStreamingProcessStartedRunner()
        runtime = _RuntimeStreamingStub(process_runner)
        runner = TestRunner(runtime, verbose=False, render_output=False)
        started_pids: list[int] = []

        completed = runner.run_tests(
            ["python", "-m", "pytest"],
            process_started_callback=lambda pid: started_pids.append(pid),
        )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(started_pids, [2468])
        self.assertTrue(callable(process_runner.calls[0]["process_started_callback"]))

    def test_run_tests_forwards_process_started_callback_to_run_fallback(self) -> None:
        process_runner = _RunOnlyProcessStartedRunner()
        runtime = _RuntimeStreamingStub(process_runner)
        runner = TestRunner(runtime, verbose=False, render_output=False)
        started_pids: list[int] = []

        completed = runner.run_tests(
            ["python", "-m", "pytest"],
            process_started_callback=lambda pid: started_pids.append(pid),
        )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(started_pids, [1357])
        self.assertTrue(callable(process_runner.calls[0]["process_started_callback"]))

    def test_run_tests_fallback_parses_stderr_only_pytest_failures(self) -> None:
        class _PytestStderrOnlyRunner:
            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cmd, cwd, env, timeout
                return subprocess.CompletedProcess(
                    args=["python", "-m", "pytest"],
                    returncode=1,
                    stdout="",
                    stderr=(
                        "FAILED tests/test_auth.py::test_login - AssertionError: expected 200, got 500\n"
                        "============================== 1 failed in 0.03s ==============================\n"
                    ),
                )

        runtime = _RuntimeStreamingStub(_PytestStderrOnlyRunner())
        runner = TestRunner(runtime, verbose=False, render_output=False)

        completed = runner.run_tests(["python", "-m", "pytest"])

        self.assertEqual(completed.returncode, 1)
        assert runner.last_result is not None
        self.assertEqual(runner.last_result.failed_tests, ["tests/test_auth.py::test_login"])
        self.assertEqual(
            runner.last_result.error_details["tests/test_auth.py::test_login"],
            "AssertionError: expected 200, got 500",
        )
        self.assertTrue(runner.last_result.counts_detected)
        self.assertEqual(runner.last_result.failed, 1)

    def test_run_tests_fallback_parses_combined_stdout_and_stderr_failure_output(self) -> None:
        class _PytestSplitStreamsRunner:
            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cmd, cwd, env, timeout
                return subprocess.CompletedProcess(
                    args=["python", "-m", "pytest"],
                    returncode=1,
                    stdout="========================= 1 failed, 2 passed in 0.04s =========================\n",
                    stderr="FAILED tests/test_auth.py::test_login - AssertionError: expected 200, got 500\n",
                )

        runtime = _RuntimeStreamingStub(_PytestSplitStreamsRunner())
        runner = TestRunner(runtime, verbose=False, render_output=False)

        completed = runner.run_tests(["python", "-m", "pytest"])

        self.assertEqual(completed.returncode, 1)
        assert runner.last_result is not None
        self.assertTrue(runner.last_result.counts_detected)
        self.assertEqual(runner.last_result.passed, 2)
        self.assertEqual(runner.last_result.failed, 1)
        self.assertEqual(runner.last_result.failed_tests, ["tests/test_auth.py::test_login"])
        self.assertEqual(
            runner.last_result.error_details["tests/test_auth.py::test_login"],
            "AssertionError: expected 200, got 500",
        )

    def test_detect_test_type_identifies_bun_run_test_as_jest_family(self) -> None:
        runtime = _RuntimeStub()
        runner = TestRunner(runtime, verbose=False)

        detected = runner._detect_test_type(["bun", "run", "test"])  # noqa: SLF001

        self.assertEqual(detected, "jest")

    def test_run_tests_uses_legacy_run_streaming_signature_without_show_spinner_kwarg(self) -> None:
        process_runner = _RunStreamingLegacyRunner()
        runtime = _RuntimeStreamingStub(process_runner)
        runner = TestRunner(runtime, verbose=False)

        completed = runner.run_tests(["python", "-m", "pytest"])

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(len(process_runner.calls), 1)
        self.assertIn(
            ("python", "-m", "pytest", "-p", "envctl_engine.test_output.pytest_progress_plugin"),
            [call["cmd"] for call in process_runner.calls],
        )

    def test_run_tests_disables_spinner_for_modern_run_streaming_signature(self) -> None:
        process_runner = _RunStreamingModernRunner()
        runtime = _RuntimeStreamingStub(process_runner)
        runner = TestRunner(runtime, verbose=False)

        completed = runner.run_tests(["python", "-m", "pytest"])

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(len(process_runner.calls), 1)
        self.assertIn(
            ("python", "-m", "pytest", "-p", "envctl_engine.test_output.pytest_progress_plugin"),
            [call["cmd"] for call in process_runner.calls],
        )
        self.assertFalse(bool(process_runner.calls[0]["show_spinner"]))
        self.assertFalse(bool(process_runner.calls[0]["echo_output"]))

    def test_run_tests_closes_stdin_for_streaming_processes(self) -> None:
        process_runner = _RunStreamingWithStdinRunner()
        runtime = _RuntimeStreamingStub(process_runner)
        runner = TestRunner(runtime, verbose=False)

        completed = runner.run_tests(["python", "-m", "pytest"])

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(len(process_runner.calls), 1)
        self.assertIs(process_runner.calls[0]["stdin"], subprocess.DEVNULL)

    def test_run_tests_instruments_bun_vitest_script_and_emits_progress_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            process_runner = _RunStreamingVitestRunner()
            runtime = _RuntimeStreamingStub(process_runner)
            runner = TestRunner(runtime, verbose=False, render_output=False)
            progress_updates: list[tuple[int, int]] = []

            completed = runner.run_tests(
                ["bun", "run", "test"],
                cwd=project_root,
                progress_callback=lambda current, total: progress_updates.append((current, total)),
            )

            self.assertEqual(completed.returncode, 0)
            self.assertEqual(len(process_runner.calls), 1)
            invoked = process_runner.calls[0]["cmd"]
            reporter_path = str(PYTHON_ROOT / "envctl_engine" / "test_output" / "vitest_progress_reporter.mjs")
            assert isinstance(invoked, tuple)
            self.assertEqual(invoked[:3], ("bun", "run", "test"))
            self.assertEqual(invoked[-3:], ("--", "--reporter=default", f"--reporter={reporter_path}"))
            self.assertEqual(progress_updates, [(-1, 47), (5, 0), (0, 179), (6, 179)])
            self.assertNotIn("ENVCTL_TEST_DISCOVERED", completed.stdout)
            self.assertNotIn("ENVCTL_TEST_COMPLETE", completed.stdout)
            self.assertNotIn("ENVCTL_TEST_TOTAL", completed.stdout)
            self.assertNotIn("ENVCTL_TEST_PROGRESS", completed.stdout)

    def test_run_tests_instruments_bun_vitest_script_with_existing_separator(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            process_runner = _RunStreamingVitestRunner()
            runtime = _RuntimeStreamingStub(process_runner)
            runner = TestRunner(runtime, verbose=False, render_output=False)

            completed = runner.run_tests(
                ["bun", "run", "test", "--", "src"],
                cwd=project_root,
            )

            self.assertEqual(completed.returncode, 0)
            self.assertEqual(len(process_runner.calls), 1)
            invoked = process_runner.calls[0]["cmd"]
            reporter_path = str(PYTHON_ROOT / "envctl_engine" / "test_output" / "vitest_progress_reporter.mjs")
            self.assertEqual(
                invoked,
                ("bun", "run", "test", "--", "src", "--reporter=default", f"--reporter={reporter_path}"),
            )


if __name__ == "__main__":
    unittest.main()
