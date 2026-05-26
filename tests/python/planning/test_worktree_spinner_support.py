from __future__ import annotations

import unittest
from types import SimpleNamespace

from envctl_engine.planning.worktree_spinner_support import (
    WorktreeSpinnerLifecycle,
    worktree_spinner_finish,
    worktree_spinner_policy,
    worktree_spinner_start,
    worktree_spinner_stop,
    worktree_spinner_update,
)


class _Spinner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def start(self) -> None:
        self.calls.append(("start", None))

    def update(self, message: str) -> None:
        self.calls.append(("update", message))

    def succeed(self, message: str) -> None:
        self.calls.append(("succeed", message))

    def fail(self, message: str) -> None:
        self.calls.append(("fail", message))


class WorktreeSpinnerSupportTests(unittest.TestCase):
    def test_spinner_lifecycle_emits_worktree_planning_events(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(env={}, _emit=lambda event, **payload: events.append((event, payload)))
        spinner = _Spinner()

        policy = worktree_spinner_policy(runtime, op_id="op-1")
        worktree_spinner_start(runtime, enabled=True, active_spinner=spinner, op_id="op-1", message="Starting")
        worktree_spinner_update(runtime, enabled=True, active_spinner=spinner, op_id="op-1", message="Updating")
        worktree_spinner_finish(runtime, enabled=True, active_spinner=spinner, op_id="op-1", message="Done")
        worktree_spinner_stop(runtime, enabled=True, op_id="op-1")

        self.assertIsNotNone(policy)
        self.assertEqual(
            spinner.calls,
            [("start", None), ("update", "Updating"), ("succeed", "Done")],
        )
        lifecycle_states = [
            payload["state"]
            for event, payload in events
            if event == "ui.spinner.lifecycle" and payload.get("component") == "worktree_planning"
        ]
        self.assertEqual(lifecycle_states, ["start", "update", "success", "stop"])

    def test_lifecycle_object_supports_setup_and_sync_emit_only_usage(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        lifecycle = WorktreeSpinnerLifecycle(
            env={},
            emit=lambda event, **payload: events.append((event, payload)),
            emit_when_disabled=True,
            include_stop_enabled=True,
        )
        spinner = _Spinner()

        policy = lifecycle.policy(op_id="op-2")
        lifecycle.start(enabled=False, active_spinner=spinner, op_id="op-2", message="Starting")
        lifecycle.update(
            enabled=False,
            active_spinner=spinner,
            op_id="op-2",
            message="Updating",
            terminal_message="Updating terminal",
        )
        lifecycle.finish(enabled=False, active_spinner=spinner, op_id="op-2", message="Done")
        lifecycle.stop(enabled=False, op_id="op-2")

        self.assertIsNotNone(policy)
        self.assertEqual(spinner.calls, [])
        lifecycle_payloads = [
            payload
            for event, payload in events
            if event == "ui.spinner.lifecycle" and payload.get("component") == "worktree_planning"
        ]
        self.assertEqual([payload["state"] for payload in lifecycle_payloads], ["start", "update", "success", "stop"])
        self.assertEqual(lifecycle_payloads[-1]["enabled"], False)


if __name__ == "__main__":
    unittest.main()
