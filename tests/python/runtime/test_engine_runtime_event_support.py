from __future__ import annotations

import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.command_router import Route  # noqa: E402
from envctl_engine.runtime.engine_runtime_event_support import (  # noqa: E402
    auto_debug_pack,
    bind_debug_run_id,
    configure_debug_recorder,
    current_session_id,
    debug_mode_from_route,
    debug_output_root,
    debug_should_auto_pack,
    emit,
    sanitize_emit_payload,
)


class EngineRuntimeEventSupportTests(unittest.TestCase):
    def test_sanitize_emit_payload_hashes_sensitive_fields(self) -> None:
        runtime = SimpleNamespace(_active_command_id="cmd-1", _debug_hash_salt="salt")

        payload = sanitize_emit_payload(runtime, "ui.input.submit", {"command": "test --foo"})

        self.assertEqual(payload["command_id"], "cmd-1")
        self.assertIn("command_hash", payload)
        self.assertIn("command_length", payload)
        self.assertNotIn("command", payload)

    def test_emit_records_event_and_notifies_listener(self) -> None:
        received: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            _active_command_id="cmd-1",
            _debug_hash_salt="salt",
            _emit_lock=threading.Lock(),
            events=[],
            _debug_recorder=None,
            _emit_listeners=[lambda event, payload: received.append((event, payload))],
            env={},
            config=SimpleNamespace(raw={}),
        )

        emit(runtime, "ui.input.submit", command="test")

        self.assertEqual(runtime.events[0]["event"], "ui.input.submit")
        self.assertEqual(received[0][0], "ui.input.submit")
        self.assertIn("command_hash", received[0][1])

    def test_debug_should_auto_pack_policies(self) -> None:
        runtime = SimpleNamespace(env={"ENVCTL_DEBUG_AUTO_PACK": "anomaly"}, config=SimpleNamespace(raw={}))

        self.assertTrue(debug_should_auto_pack(runtime, reason="input_anomaly"))
        self.assertFalse(debug_should_auto_pack(runtime, reason="normal"))

    def test_auto_debug_pack_emits_status_when_enabled(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            env={"ENVCTL_DEBUG_AUTO_PACK": "always"},
            config=SimpleNamespace(raw={}),
            _debug_pack=lambda route: 0,
            _last_debug_bundle_path="/tmp/bundle.tgz",
            _emit=lambda event, **payload: events.append((event, payload)),
        )

        auto_debug_pack(runtime, reason="dispatch_exception")

        self.assertEqual(
            events,
            [("debug.auto_pack", {"reason": "dispatch_exception", "success": True, "bundle_path": "/tmp/bundle.tgz"})],
        )

    def test_current_session_id_trims_value(self) -> None:
        runtime = SimpleNamespace(_debug_recorder=SimpleNamespace(session_id="  session-1  "))

        self.assertEqual(current_session_id(runtime), "session-1")

    def test_debug_mode_from_route_and_output_root(self) -> None:
        route = Route(
            command="start", mode="main", raw_args=[], passthrough_args=[], projects=[], flags={"debug_ui": True}
        )
        runtime = SimpleNamespace(
            env={"ENVCTL_DEBUG_UI_PATH": "tmp/debug"},
            config=SimpleNamespace(raw={}, base_dir=Path("/repo")),
        )

        self.assertEqual(debug_mode_from_route(runtime, route), "standard")
        self.assertEqual(debug_output_root(runtime), Path("/repo/tmp/debug"))

    def test_bind_debug_run_id_updates_env_and_recorder(self) -> None:
        calls: list[str] = []
        runtime = SimpleNamespace(env={}, _debug_recorder=SimpleNamespace(set_run_id=lambda value: calls.append(value)))

        bind_debug_run_id(runtime, "run-1")

        self.assertEqual(runtime.env["ENVCTL_DEBUG_UI_RUN_ID"], "run-1")
        self.assertEqual(calls, ["run-1"])

    def test_configure_debug_recorder_builds_recorder(self) -> None:
        route = Route(
            command="start", mode="main", raw_args=[], passthrough_args=[], projects=[], flags={"debug_ui_deep": True}
        )
        runtime = SimpleNamespace(
            env={},
            config=SimpleNamespace(raw={}, runtime_scope_id="repo-1", base_dir=Path("/repo")),
            runtime_root=Path("/tmp/runtime"),
            _debug_hash_salt="salt",
            _debug_recorder=None,
        )

        class FakeRecorder:
            def __init__(self, config):  # noqa: ANN001
                self.config = config
                self.run_ids: list[str | None] = []

            def set_run_id(self, value):  # noqa: ANN001
                self.run_ids.append(value)

        with patch("envctl_engine.runtime.engine_runtime_event_support.DebugFlightRecorder", FakeRecorder):
            configure_debug_recorder(runtime, route)

        self.assertEqual(runtime.env["ENVCTL_DEBUG_UI_MODE"], "deep")
        self.assertIsNotNone(runtime._debug_recorder)
        self.assertEqual(runtime._debug_recorder.config.mode, "deep")


if __name__ == "__main__":
    unittest.main()
