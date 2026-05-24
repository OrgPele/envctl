from __future__ import annotations

from types import SimpleNamespace
import unittest

from envctl_engine.actions.action_spinner_support import install_action_spinner_status_bridge


class _Spinner:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def update(self, message: str) -> None:
        self.messages.append(message)


class ActionSpinnerSupportTests(unittest.TestCase):
    def test_install_action_spinner_status_bridge_uses_emit_listener_when_available(self) -> None:
        listeners: list[object] = []
        emitted: list[dict[str, object]] = []
        spinner = _Spinner()

        def add_emit_listener(listener: object):
            listeners.append(listener)

            def remove() -> None:
                listeners.remove(listener)

            return remove

        runtime_raw = SimpleNamespace(add_emit_listener=add_emit_listener)
        runtime = SimpleNamespace(
            raw_runtime=runtime_raw,
            emit=lambda event_name, **payload: emitted.append({"event": event_name, **payload}),
        )

        restore = install_action_spinner_status_bridge(
            runtime=runtime,
            command="test",
            op_id="op-1",
            active_spinner=spinner,
        )

        self.assertEqual(len(listeners), 1)
        listeners[0]("ui.status", {"message": "Running tests..."})
        self.assertEqual(spinner.messages, ["Running tests..."])
        self.assertEqual(
            emitted,
            [
                {
                    "event": "ui.spinner.lifecycle",
                    "component": "action.command",
                    "command": "test",
                    "op_id": "op-1",
                    "state": "update",
                    "message": "Running tests...",
                }
            ],
        )
        restore()
        self.assertEqual(listeners, [])

    def test_install_action_spinner_status_bridge_wraps_legacy_emit_when_listener_missing(self) -> None:
        spinner = _Spinner()
        emitted: list[dict[str, object]] = []

        def raw_emit(event_name: str, **payload: object) -> None:
            emitted.append({"event": event_name, **payload})

        runtime_raw = SimpleNamespace(_emit=raw_emit)
        runtime = SimpleNamespace(
            raw_runtime=runtime_raw,
            emit=lambda event_name, **payload: emitted.append({"event": event_name, **payload}),
        )

        restore = install_action_spinner_status_bridge(
            runtime=runtime,
            command="review",
            op_id="op-2",
            active_spinner=spinner,
        )

        runtime_raw._emit("ui.status", message="Reviewing...")
        self.assertEqual(spinner.messages, ["Reviewing..."])
        self.assertEqual(emitted[0], {"event": "ui.status", "message": "Reviewing..."})
        self.assertEqual(emitted[1]["event"], "ui.spinner.lifecycle")
        restore()
        self.assertIs(runtime_raw._emit, raw_emit)


if __name__ == "__main__":
    unittest.main()
