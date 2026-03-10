from __future__ import annotations

from contextlib import contextmanager
import io
import subprocess
import unittest
from unittest.mock import patch

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.shared.process_runner import ProcessRunner


class _FakePopen:
    def __init__(self, lines: str, returncode: int = 0) -> None:
        self.stdout = io.StringIO(lines)
        self._returncode = returncode

    def wait(self, timeout: float | None = None) -> int:
        _ = timeout
        return self._returncode

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        _ = timeout
        return self.stdout.getvalue(), ""

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        return None


class _InfiniteStdout:
    def readline(self) -> str:
        return "line-1\n"


class _NeverEndingPopen:
    def __init__(self) -> None:
        self.stdout = _InfiniteStdout()

    def wait(self, timeout: float | None = None) -> int:
        _ = timeout
        return 0

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        return None


class ProcessRunnerSpinnerIntegrationTests(unittest.TestCase):
    def test_run_streaming_uses_spinner_context_not_threaded_manager(self) -> None:
        runner = ProcessRunner()
        spinner_calls: list[tuple[str, bool]] = []

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            _ = start_immediately
            spinner_calls.append((message, enabled))

            class _SpinnerStub:
                def update(self, _message: str) -> None:
                    return None

                def succeed(self, _message: str) -> None:
                    return None

                def fail(self, _message: str) -> None:
                    return None

            yield _SpinnerStub()

        with (
            patch("envctl_engine.shared.process_runner.spinner", side_effect=fake_spinner),
            patch("envctl_engine.shared.process_runner.spinner_enabled", return_value=True),
            patch("envctl_engine.shared.process_runner.subprocess.Popen", return_value=_FakePopen("line-1\nline-2\n")),
        ):
            completed = runner.run_streaming(["echo", "hello"], callback=None)

        self.assertEqual(completed.returncode, 0)
        self.assertIn("line-1", completed.stdout)
        self.assertEqual(len(spinner_calls), 1)
        self.assertEqual(spinner_calls[0][1], True)

    def test_run_streaming_verbose_callback_prints_lines_and_spins(self) -> None:
        runner = ProcessRunner()
        seen_lines: list[str] = []

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            _ = message, enabled, start_immediately

            class _SpinnerStub:
                def update(self, _message: str) -> None:
                    return None

                def succeed(self, _message: str) -> None:
                    return None

                def fail(self, _message: str) -> None:
                    return None

            yield _SpinnerStub()

        with (
            patch("envctl_engine.shared.process_runner.spinner", side_effect=fake_spinner),
            patch("envctl_engine.shared.process_runner.spinner_enabled", return_value=True),
            patch("envctl_engine.shared.process_runner.subprocess.Popen", return_value=_FakePopen("line-a\nline-b\n")),
            patch("builtins.print") as print_mock,
        ):
            completed = runner.run_streaming(["echo", "hello"], callback=lambda line: seen_lines.append(line))

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(seen_lines, ["line-a", "line-b"])
        printed_lines = [str(call.args[0]) for call in print_mock.call_args_list if call.args]
        self.assertIn("line-a", printed_lines)
        self.assertIn("line-b", printed_lines)

    def test_run_streaming_no_spinner_does_not_emit_failed_terminal_line(self) -> None:
        runner = ProcessRunner()

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            _ = message, start_immediately

            class _SpinnerStub:
                def update(self, _message: str) -> None:
                    return None

                def succeed(self, _message: str) -> None:
                    return None

                def fail(self, _message: str) -> None:
                    return None

            self.assertFalse(enabled)
            yield _SpinnerStub()

        with (
            patch("envctl_engine.shared.process_runner.spinner", side_effect=fake_spinner),
            patch("envctl_engine.shared.process_runner.spinner_enabled", return_value=True),
            patch(
                "envctl_engine.shared.process_runner.subprocess.Popen", return_value=_FakePopen("line\n", returncode=1)
            ),
            patch("builtins.print") as print_mock,
        ):
            completed = runner.run_streaming(["echo", "hello"], callback=None, show_spinner=False)

        self.assertEqual(completed.returncode, 1)
        printed = [str(call.args[0]) for call in print_mock.call_args_list if call.args]
        self.assertFalse(any("Command failed" in line for line in printed), msg=printed)
        self.assertFalse(any(line.startswith("! ") for line in printed), msg=printed)

    def test_run_streaming_timeout_without_spinner_does_not_emit_timeout_line(self) -> None:
        runner = ProcessRunner()
        timeout_state = {"now": 0.0}

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            _ = message, start_immediately

            class _SpinnerStub:
                def update(self, _message: str) -> None:
                    return None

                def succeed(self, _message: str) -> None:
                    return None

                def fail(self, _message: str) -> None:
                    return None

            self.assertFalse(enabled)
            yield _SpinnerStub()

        def fake_time() -> float:
            timeout_state["now"] += 10.0
            return timeout_state["now"]

        with (
            patch("envctl_engine.shared.process_runner.spinner", side_effect=fake_spinner),
            patch("envctl_engine.shared.process_runner.spinner_enabled", return_value=True),
            patch("envctl_engine.shared.process_runner.subprocess.Popen", return_value=_NeverEndingPopen()),
            patch("envctl_engine.shared.process_runner.time.time", side_effect=fake_time),
            patch("builtins.print") as print_mock,
        ):
            completed = runner.run_streaming(["echo", "hello"], callback=None, show_spinner=False, timeout=1.0)

        self.assertEqual(completed.returncode, -1)
        printed = [str(call.args[0]) for call in print_mock.call_args_list if call.args]
        self.assertFalse(any("Command timed out" in line for line in printed), msg=printed)
        self.assertFalse(any(line.startswith("! ") for line in printed), msg=printed)

    def test_run_streaming_passes_stdin_configuration_to_subprocess(self) -> None:
        runner = ProcessRunner()
        popen_calls: list[dict[str, object]] = []

        def fake_popen(*args, **kwargs):  # noqa: ANN001
            popen_calls.append({"args": args, "kwargs": kwargs})
            return _FakePopen("line-1\n")

        with (
            patch("envctl_engine.shared.process_runner.spinner_enabled", return_value=False),
            patch("envctl_engine.shared.process_runner.subprocess.Popen", side_effect=fake_popen),
        ):
            completed = runner.run_streaming(["echo", "hello"], callback=None, stdin=subprocess.DEVNULL)

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(len(popen_calls), 1)
        self.assertIs(popen_calls[0]["kwargs"]["stdin"], subprocess.DEVNULL)
        self.assertTrue(bool(popen_calls[0]["kwargs"]["start_new_session"]))


if __name__ == "__main__":
    unittest.main()
