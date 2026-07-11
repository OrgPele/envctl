from __future__ import annotations

import os
import signal
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.shared.process_termination import terminate_pid


class ProcessTerminationTests(unittest.TestCase):
    def test_terminate_pid_refuses_self_and_parent_without_signalling(self) -> None:
        runner = SimpleNamespace(
            is_pid_running=lambda _pid: True,
            terminate_process_group=lambda *_args, **_kwargs: self.fail("protected PID must not be signalled"),
        )

        self.assertFalse(terminate_pid(os.getpid(), process_runner=runner, term_timeout=0.0, kill_timeout=0.0))
        self.assertFalse(terminate_pid(os.getppid(), process_runner=runner, term_timeout=0.0, kill_timeout=0.0))

    def test_failed_group_termination_does_not_kill_only_the_leader(self) -> None:
        runner_calls: list[str] = []
        sent: list[signal.Signals] = []
        runner = SimpleNamespace(
            is_pid_running=lambda _pid: True,
            terminate_process_group=lambda *_args, **_kwargs: runner_calls.append("group") or False,
            terminate=lambda *_args, **_kwargs: runner_calls.append("single") or False,
        )

        with (
            patch(
                "envctl_engine.shared.process_termination._send_signal",
                side_effect=lambda _pid, requested_signal: sent.append(requested_signal) or True,
            ),
            patch("envctl_engine.shared.process_termination.wait_for_pid_exit", side_effect=[False, False]),
        ):
            result = terminate_pid(987654, process_runner=runner, term_timeout=0.0, kill_timeout=0.0)

        self.assertFalse(result)
        self.assertEqual(runner_calls, ["group"])
        self.assertEqual(sent, [])

    def test_runner_without_group_support_falls_back_to_raw_signals(self) -> None:
        sent: list[signal.Signals] = []
        runner = SimpleNamespace(
            is_pid_running=lambda _pid: True,
            terminate=lambda *_args, **_kwargs: False,
        )

        with (
            patch(
                "envctl_engine.shared.process_termination._send_signal",
                side_effect=lambda _pid, requested_signal: sent.append(requested_signal) or True,
            ),
            patch("envctl_engine.shared.process_termination.wait_for_pid_exit", side_effect=[False, False]),
        ):
            result = terminate_pid(987654, process_runner=runner, term_timeout=0.0, kill_timeout=0.0)

        self.assertFalse(result)
        self.assertEqual(sent, [signal.SIGTERM, signal.SIGKILL])

    def test_runner_success_is_not_trusted_while_same_identified_pid_remains_live(self) -> None:
        sent: list[signal.Signals] = []
        runner = SimpleNamespace(
            is_pid_running=lambda _pid: True,
            _pid_identity=lambda _pid: "original",
            terminate_process_group=lambda *_args, **_kwargs: True,
        )

        with patch(
            "envctl_engine.shared.process_termination._send_signal",
            side_effect=lambda _pid, requested_signal: sent.append(requested_signal) or True,
        ):
            result = terminate_pid(987655, process_runner=runner, term_timeout=0.0, kill_timeout=0.0)

        self.assertFalse(result)
        self.assertEqual(sent, [])

    def test_identity_incapable_runner_success_is_not_trusted_while_pid_remains_live(self) -> None:
        runner = SimpleNamespace(
            is_pid_running=lambda _pid: True,
            terminate_process_group=lambda *_args, **_kwargs: True,
        )

        result = terminate_pid(987657, process_runner=runner, term_timeout=0.0, kill_timeout=0.0)

        self.assertFalse(result)

    def test_identity_replacement_after_failed_group_cleanup_is_not_reported_as_success(self) -> None:
        identities = iter(("original", "replacement"))
        sent: list[signal.Signals] = []
        runner = SimpleNamespace(
            is_pid_running=lambda _pid: True,
            _pid_identity=lambda _pid: next(identities),
            terminate_process_group=lambda *_args, **_kwargs: False,
        )

        with patch(
            "envctl_engine.shared.process_termination._send_signal",
            side_effect=lambda _pid, requested_signal: sent.append(requested_signal) or True,
        ):
            result = terminate_pid(987656, process_runner=runner, term_timeout=0.0, kill_timeout=0.0)

        self.assertFalse(result)
        self.assertEqual(sent, [])

    def test_group_cleanup_exception_is_success_after_leader_replacement(self) -> None:
        identities = iter(("original", "replacement"))
        sent: list[signal.Signals] = []
        runner = SimpleNamespace(
            is_pid_running=lambda _pid: True,
            _pid_identity=lambda _pid: next(identities),
            terminate_process_group=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("post-kill reporting failed")
            ),
        )

        with patch(
            "envctl_engine.shared.process_termination._send_signal",
            side_effect=lambda _pid, requested_signal: sent.append(requested_signal) or True,
        ):
            result = terminate_pid(987658, process_runner=runner, term_timeout=0.0, kill_timeout=0.0)

        self.assertTrue(result)
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
