from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.shared.process_runner import ProcessRunner


class ProcessRunnerLaunchPolicyTests(unittest.TestCase):
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
