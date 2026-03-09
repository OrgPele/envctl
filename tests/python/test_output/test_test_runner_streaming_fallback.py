from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

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


class _RuntimeStreamingStub:
    def __init__(self, process_runner) -> None:  # noqa: ANN001
        self.process_runner = process_runner


class TestRunnerStreamingFallbackTests(unittest.TestCase):
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
                [str(REPO_ROOT / ".venv" / "bin" / "python"), "-m", "pytest", "tests"],
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


if __name__ == "__main__":
    unittest.main()
