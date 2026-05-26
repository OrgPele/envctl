from __future__ import annotations

from typing import Any, Mapping
import unittest

from envctl_engine.ui.command_loop_spinner import (
    CommandSpinnerTracker,
    command_spinner_message,
    install_spinner_event_bridge,
    spinner_failure_message_for_event,
    spinner_message_for_event,
)


class _SpinnerStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def start(self) -> None:
        self.calls.append(("start", ""))

    def update(self, message: str) -> None:
        self.calls.append(("update", message))

    def end(self) -> None:
        self.calls.append(("end", ""))


class _RuntimeWithListener:
    def __init__(self) -> None:
        self.listeners: list[Any] = []
        self.env: dict[str, str] = {}

    def add_emit_listener(self, listener: Any):
        self.listeners.append(listener)

        def remove() -> None:
            self.listeners.remove(listener)

        return remove

    def emit(self, event_name: str, **payload: object) -> None:
        for listener in list(self.listeners):
            listener(event_name, payload)


class _RuntimeWithEmitOnly:
    def __init__(self) -> None:
        self.events: list[tuple[str, Mapping[str, object]]] = []
        self.env: dict[str, str] = {}

    def _emit(self, event_name: str, **payload: object) -> None:
        self.events.append((event_name, payload))


class CommandLoopSpinnerSupportTests(unittest.TestCase):
    def test_command_spinner_message_uses_command_specific_copy(self) -> None:
        self.assertEqual(command_spinner_message("test"), "Preparing tests...")
        self.assertEqual(command_spinner_message("pr"), "Preparing pull request workflow...")
        self.assertEqual(command_spinner_message(None), "Running command...")
        self.assertEqual(command_spinner_message("unknown"), "Running unknown...")

    def test_spinner_event_messages_cover_runtime_progress_and_failure_events(self) -> None:
        self.assertEqual(
            spinner_message_for_event(
                "startup.execution",
                {"projects": ["one", "two"], "mode": "fullstack", "workers": "2"},
            ),
            "Starting 2 project(s) in fullstack mode (2 workers)...",
        )
        self.assertEqual(
            spinner_message_for_event("state.action.start", {"command": "health", "service_count": 3}),
            "Checking health for 3 service(s)...",
        )
        self.assertEqual(
            spinner_failure_message_for_event("action.command.finish", {"command": "test", "code": "2"}),
            "test failed (exit 2)",
        )

    def test_event_bridge_uses_runtime_listener_without_replacing_emit(self) -> None:
        runtime = _RuntimeWithListener()
        spinner = _SpinnerStub()
        tracker = CommandSpinnerTracker()

        restore = install_spinner_event_bridge(
            runtime=runtime,
            active_spinner=spinner,
            tracker=tracker,
            command_id="cmd-1",
        )

        runtime.emit("action.command.start", command="test")
        runtime.emit("ui.status", message="Running tests...")
        runtime.emit("action.command.finish", command="test", code=1)
        restore()

        self.assertEqual(
            spinner.calls,
            [
                ("start", ""),
                ("update", "Running test..."),
                ("update", "Running tests..."),
                ("update", "test failed (exit 1)"),
            ],
        )
        self.assertTrue(tracker.started)
        self.assertTrue(tracker.failed)
        self.assertEqual(runtime.listeners, [])

    def test_event_bridge_preserves_emit_only_compatibility_path(self) -> None:
        runtime = _RuntimeWithEmitOnly()
        spinner = _SpinnerStub()
        tracker = CommandSpinnerTracker()
        original_emit = runtime._emit

        restore = install_spinner_event_bridge(
            runtime=runtime,
            active_spinner=spinner,
            tracker=tracker,
            command_id="cmd-2",
        )
        runtime._emit("action.command.start", command="restart")
        restore()

        self.assertIs(runtime._emit.__self__, original_emit.__self__)
        self.assertIs(runtime._emit.__func__, original_emit.__func__)
        self.assertEqual(runtime.events, [("action.command.start", {"command": "restart"})])
        self.assertEqual(spinner.calls, [("start", ""), ("update", "Running restart...")])


if __name__ == "__main__":
    unittest.main()
