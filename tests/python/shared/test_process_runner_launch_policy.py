from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.shared.process_runner import ProcessHandoffCleanupError, ProcessRunner


def _force_process_cleanup(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            try:
                process.kill()
            except OSError:
                pass
    try:
        process.wait(timeout=5.0)
    except (ChildProcessError, ProcessLookupError, subprocess.TimeoutExpired):
        pass


def _wait_for_path(path: Path, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return
        time.sleep(0.01)
    raise AssertionError(f"child readiness marker was not created: {path}")


def _sigterm_ignoring_command(ready_path: Path) -> list[str]:
    source = (
        "import pathlib, signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"pathlib.Path({str(ready_path)!r}).write_text('ready', encoding='utf-8'); "
        "time.sleep(60)"
    )
    return [sys.executable, "-c", source]


class ProcessRunnerLaunchPolicyTests(unittest.TestCase):
    def test_unconfirmed_background_cleanup_preserves_pid_authority(self) -> None:
        class UnkillableProcess:
            pid = 987_654
            returncode = None

            def poll(self) -> None:
                return None

            def wait(self, timeout: float | None = None) -> int:
                raise subprocess.TimeoutExpired(cmd=["fake-service"], timeout=timeout or 0.0)

            def terminate(self) -> None:
                raise PermissionError("terminate denied")

            def kill(self) -> None:
                raise PermissionError("kill denied")

        process = UnkillableProcess()
        runner = ProcessRunner(emit=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("emit failed")))

        with (
            patch(
                "envctl_engine.shared.process_launch_support.subprocess.Popen",
                return_value=process,
            ),
            patch(
                "envctl_engine.shared.process_launch_support.os.killpg",
                side_effect=PermissionError("killpg denied"),
            ),
            self.assertRaises(ProcessHandoffCleanupError) as raised,
        ):
            runner.start_background(["fake-service"])

        self.assertIs(raised.exception.process, process)
        self.assertEqual(raised.exception.pid, process.pid)
        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        self.assertTrue(runner._launch_records[-1].active)  # noqa: SLF001
        with patch.object(runner, "is_pid_running", return_value=True):
            self.assertEqual(runner.launch_diagnostics_summary()["active_launch_count"], 1)

    def test_unconfirmed_run_cleanup_preserves_pid_authority(self) -> None:
        class UnkillableProcess:
            pid = 987_655
            returncode = None

            def communicate(self, timeout: float | None = None) -> tuple[str, str]:
                _ = timeout
                raise KeyboardInterrupt

            def poll(self) -> None:
                return None

            def wait(self, timeout: float | None = None) -> int:
                raise subprocess.TimeoutExpired(cmd=["fake-command"], timeout=timeout or 0.0)

            def terminate(self) -> None:
                raise PermissionError("terminate denied")

            def kill(self) -> None:
                raise PermissionError("kill denied")

        process = UnkillableProcess()
        runner = ProcessRunner()

        with (
            patch(
                "envctl_engine.shared.process_runner.subprocess.Popen",
                return_value=process,
            ),
            patch(
                "envctl_engine.shared.process_launch_support.os.killpg",
                side_effect=PermissionError("killpg denied"),
            ),
            self.assertRaises(ProcessHandoffCleanupError) as raised,
        ):
            runner.run(["fake-command"])

        self.assertIs(raised.exception.process, process)
        self.assertEqual(raised.exception.pid, process.pid)
        self.assertIsInstance(raised.exception.__cause__, KeyboardInterrupt)
        record = runner._launch_records[-1]  # noqa: SLF001
        self.assertEqual(record.launch_intent, "foreground_cleanup_unconfirmed")
        self.assertTrue(record.active)
        with patch.object(runner, "is_pid_running", return_value=True):
            self.assertEqual(runner.launch_diagnostics_summary()["active_launch_count"], 1)

    def test_unconfirmed_timeout_cleanup_never_returns_completed_result(self) -> None:
        class UnkillableTimedOutProcess:
            pid = 987_656
            returncode = None

            def communicate(self, timeout: float | None = None) -> tuple[str, str]:
                raise subprocess.TimeoutExpired(cmd=["fake-command"], timeout=timeout or 0.0)

            def poll(self) -> None:
                return None

            def wait(self, timeout: float | None = None) -> int:
                raise subprocess.TimeoutExpired(cmd=["fake-command"], timeout=timeout or 0.0)

            def terminate(self) -> None:
                raise PermissionError("terminate denied")

            def kill(self) -> None:
                raise PermissionError("kill denied")

        process = UnkillableTimedOutProcess()
        runner = ProcessRunner()

        with (
            patch(
                "envctl_engine.shared.process_runner.subprocess.Popen",
                return_value=process,
            ),
            patch(
                "envctl_engine.shared.process_runner.os.killpg",
                side_effect=PermissionError("killpg denied"),
            ),
            patch(
                "envctl_engine.shared.process_launch_support.os.killpg",
                side_effect=PermissionError("killpg denied"),
            ),
            self.assertRaises(ProcessHandoffCleanupError) as raised,
        ):
            runner.run(["fake-command"], timeout=0.01)

        self.assertIs(raised.exception.process, process)
        self.assertEqual(raised.exception.pid, process.pid)
        self.assertIsInstance(raised.exception.__cause__, subprocess.TimeoutExpired)
        self.assertEqual(
            runner._launch_records[-1].launch_intent,  # noqa: SLF001
            "foreground_cleanup_unconfirmed",
        )

    @unittest.skipUnless(hasattr(os, "killpg"), "requires POSIX process groups")
    def test_interactive_emit_failure_terminates_real_child_before_reraising(self) -> None:
        real_popen = subprocess.Popen
        spawned: list[subprocess.Popen[str]] = []

        with tempfile.TemporaryDirectory() as tmpdir:
            ready_path = Path(tmpdir) / "ready"
            command = _sigterm_ignoring_command(ready_path)

            def capture_popen(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
                process = real_popen(*args, **kwargs)
                spawned.append(process)
                return process

            def fail_emit(_event: str, **_payload: object) -> None:
                _wait_for_path(ready_path)
                raise RuntimeError("emit interrupted")

            runner = ProcessRunner(emit=fail_emit)
            try:
                with (
                    patch(
                        "envctl_engine.shared.process_launch_support.subprocess.Popen",
                        side_effect=capture_popen,
                    ),
                    self.assertRaisesRegex(RuntimeError, "emit interrupted"),
                ):
                    runner.start_interactive_child(command)

                self.assertEqual(len(spawned), 1)
                self.assertEqual(spawned[0].poll(), -signal.SIGKILL)
            finally:
                _force_process_cleanup(spawned[0] if spawned else None)

    @unittest.skipUnless(hasattr(os, "killpg"), "requires POSIX process groups")
    def test_start_background_emit_failures_terminate_real_child_before_reraising(self) -> None:
        real_popen = subprocess.Popen

        for failure_type in (RuntimeError, KeyboardInterrupt):
            with self.subTest(failure_type=failure_type.__name__):
                with tempfile.TemporaryDirectory() as tmpdir:
                    ready_path = Path(tmpdir) / "ready"
                    command = _sigterm_ignoring_command(ready_path)
                    spawned: list[subprocess.Popen[str]] = []

                    def capture_popen(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
                        process = real_popen(*args, **kwargs)
                        spawned.append(process)
                        return process

                    def fail_emit(_event: str, **_payload: object) -> None:
                        _wait_for_path(ready_path)
                        raise failure_type("emit interrupted")

                    runner = ProcessRunner(emit=fail_emit)
                    try:
                        with (
                            patch(
                                "envctl_engine.shared.process_launch_support.subprocess.Popen",
                                side_effect=capture_popen,
                            ),
                            self.assertRaises(failure_type),
                        ):
                            runner.start_background(command)

                        self.assertEqual(len(spawned), 1)
                        self.assertEqual(spawned[0].poll(), -signal.SIGKILL)
                        self.assertFalse(runner._launch_records[-1].active)  # noqa: SLF001
                        self.assertEqual(runner.launch_diagnostics_summary()["active_launch_count"], 0)
                    finally:
                        _force_process_cleanup(spawned[0] if spawned else None)

    @unittest.skipUnless(hasattr(os, "killpg"), "requires POSIX process groups")
    def test_run_communicate_failures_terminate_real_child_before_reraising(self) -> None:
        real_popen = subprocess.Popen

        for failure_type in (RuntimeError, KeyboardInterrupt):
            with self.subTest(failure_type=failure_type.__name__):
                with tempfile.TemporaryDirectory() as tmpdir:
                    ready_path = Path(tmpdir) / "ready"
                    command = _sigterm_ignoring_command(ready_path)
                    spawned: list[subprocess.Popen[str]] = []

                    class InterruptingProcess:
                        def __init__(self, process: subprocess.Popen[str]) -> None:
                            self.process = process

                        @property
                        def pid(self) -> int:
                            return self.process.pid

                        @property
                        def returncode(self) -> int | None:
                            return self.process.returncode

                        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
                            _ = timeout
                            _wait_for_path(ready_path)
                            raise failure_type("communicate interrupted")

                        def poll(self) -> int | None:
                            return self.process.poll()

                        def wait(self, timeout: float | None = None) -> int:
                            return self.process.wait(timeout=timeout)

                        def terminate(self) -> None:
                            self.process.terminate()

                        def kill(self) -> None:
                            self.process.kill()

                    def capture_popen(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
                        process = real_popen(*args, **kwargs)
                        spawned.append(process)
                        return InterruptingProcess(process)

                    runner = ProcessRunner()
                    try:
                        with (
                            patch(
                                "envctl_engine.shared.process_runner.subprocess.Popen",
                                side_effect=capture_popen,
                            ),
                            self.assertRaises(failure_type),
                        ):
                            runner.run(command)

                        self.assertEqual(len(spawned), 1)
                        self.assertEqual(spawned[0].poll(), -signal.SIGKILL)
                    finally:
                        _force_process_cleanup(spawned[0] if spawned else None)

    def test_start_background_denies_controller_input_and_emits_launch_policy(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runner = ProcessRunner(emit=lambda event, **payload: events.append((event, dict(payload))))

        with tempfile.TemporaryDirectory() as tmpdir:
            stdout_path = Path(tmpdir) / "service.log"
            with patch(
                "envctl_engine.shared.process_runner.subprocess.Popen",
                return_value=SimpleNamespace(pid=1234),
            ) as popen_mock:
                runner.start_background(
                    ["python", "app.py"],
                    cwd=tmpdir,
                    env={"APP_ENV": "test"},
                    stdout_path=stdout_path,
                    stderr_path=stdout_path,
                )

        kwargs = popen_mock.call_args.kwargs
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertTrue(bool(kwargs["start_new_session"]))
        self.assertTrue(any(name == "process.launch" for name, _payload in events))
        launch_event = [payload for name, payload in events if name == "process.launch"][-1]
        self.assertEqual(launch_event["launch_intent"], "background_service")
        self.assertEqual(launch_event["stdin_policy"], "devnull")
        self.assertFalse(bool(launch_event["controller_input_owner_allowed"]))
        self.assertEqual(launch_event["stdout_policy"], "file")
        self.assertEqual(launch_event["stderr_policy"], "file")

    def test_run_probe_denies_controller_input_and_emits_probe_launch_policy(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runner = ProcessRunner(emit=lambda event, **payload: events.append((event, dict(payload))))

        with patch(
            "envctl_engine.shared.process_runner.subprocess.run",
            return_value=subprocess.CompletedProcess(["ps"], 0, "123 1\n", ""),
        ) as run_mock:
            completed = runner.run_probe(["ps", "-axo", "pid=,ppid="])

        self.assertEqual(completed.returncode, 0)
        kwargs = run_mock.call_args.kwargs
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.PIPE)
        self.assertIs(kwargs["stderr"], subprocess.PIPE)
        launch_event = [payload for name, payload in events if name == "process.launch"][-1]
        self.assertEqual(launch_event["launch_intent"], "probe")
        self.assertEqual(launch_event["stdin_policy"], "devnull")
        self.assertFalse(bool(launch_event["controller_input_owner_allowed"]))

    def test_interactive_child_is_explicit_opt_in_for_controller_input(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runner = ProcessRunner(emit=lambda event, **payload: events.append((event, dict(payload))))

        with patch(
            "envctl_engine.shared.process_runner.subprocess.Popen",
            return_value=SimpleNamespace(pid=2222),
        ) as popen_mock:
            runner.start_interactive_child(["python", "-c", "print('ok')"])

        kwargs = popen_mock.call_args.kwargs
        self.assertIsNone(kwargs["stdin"])
        launch_event = [payload for name, payload in events if name == "process.launch"][-1]
        self.assertEqual(launch_event["launch_intent"], "interactive_child")
        self.assertEqual(launch_event["stdin_policy"], "inherit")
        self.assertTrue(bool(launch_event["controller_input_owner_allowed"]))

    def test_launch_diagnostics_summary_reports_active_controller_input_owners(self) -> None:
        runner = ProcessRunner()
        runner._launch_records.extend(  # noqa: SLF001
            [
                SimpleNamespace(
                    launch_intent="background_service",
                    pid=3001,
                    command_hash="a",
                    command_length=1,
                    cwd="/tmp/a",
                    stdin_policy="devnull",
                    stdout_policy="file",
                    stderr_policy="file",
                    controller_input_owner_allowed=False,
                    active=True,
                ),
                SimpleNamespace(
                    launch_intent="interactive_child",
                    pid=3002,
                    command_hash="b",
                    command_length=1,
                    cwd="/tmp/b",
                    stdin_policy="inherit",
                    stdout_policy="inherit",
                    stderr_policy="inherit",
                    controller_input_owner_allowed=True,
                    active=True,
                ),
            ]
        )

        with patch.object(runner, "is_pid_running", side_effect=lambda pid: pid in {3001, 3002}):
            summary = runner.launch_diagnostics_summary()

        self.assertEqual(summary["tracked_launch_count"], 2)
        self.assertEqual(summary["launch_intent_counts"], {"background_service": 1, "interactive_child": 1})
        active_input_owners = summary["active_controller_input_owners"]
        self.assertEqual(len(active_input_owners), 1)
        self.assertEqual(active_input_owners[0]["launch_intent"], "interactive_child")


if __name__ == "__main__":
    unittest.main()
