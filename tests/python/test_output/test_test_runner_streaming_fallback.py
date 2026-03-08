from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

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

    def run_streaming(self, cmd, *, cwd=None, env=None, timeout=None, callback=None, show_spinner=True):  # noqa: ANN001
        _ = cwd, env, timeout
        self.calls.append(
            {
                "cmd": tuple(str(part) for part in cmd),
                "callback": callback,
                "show_spinner": show_spinner,
            }
        )
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
    def test_run_tests_falls_back_to_run_when_run_streaming_missing(self) -> None:
        runtime = _RuntimeStub()
        runner = TestRunner(runtime, verbose=False)

        completed = runner.run_tests(["python", "-m", "pytest"])

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(len(runtime.process_runner.calls), 1)
        self.assertIn(("python", "-m", "pytest"), runtime.process_runner.calls)

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
        self.assertIn(("python", "-m", "pytest"), [call["cmd"] for call in process_runner.calls])

    def test_run_tests_disables_spinner_for_modern_run_streaming_signature(self) -> None:
        process_runner = _RunStreamingModernRunner()
        runtime = _RuntimeStreamingStub(process_runner)
        runner = TestRunner(runtime, verbose=False)

        completed = runner.run_tests(["python", "-m", "pytest"])

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(len(process_runner.calls), 1)
        self.assertIn(("python", "-m", "pytest"), [call["cmd"] for call in process_runner.calls])
        self.assertFalse(bool(process_runner.calls[0]["show_spinner"]))


if __name__ == "__main__":
    unittest.main()
