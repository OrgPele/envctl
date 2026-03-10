from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.ui.debug_flight_recorder import DebugFlightRecorder, DebugRecorderConfig


class DebugFlightRecorderSchemaTests(unittest.TestCase):
    def test_recorder_writes_required_event_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DebugRecorderConfig(
                runtime_scope_dir=Path(tmpdir) / "scope",
                runtime_scope_id="repo-123",
                run_id="run-1",
                mode="standard",
                bundle_strict=True,
                capture_printable=False,
                ring_bytes=256,
                max_events=10,
                sample_rate=1,
            )
            recorder = DebugFlightRecorder(config)
            recorder.record("ui.input.read.begin", component="test", backend="prompt_toolkit")

            raw = recorder.events_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(raw), 1)
            event = json.loads(raw[0])
            for key in (
                "event",
                "ts_wall",
                "ts_mono_ns",
                "seq",
                "session_id",
                "run_id",
                "pid",
                "thread",
                "scope_id",
                "mode",
                "component",
                "trace_id",
                "schema_version",
            ):
                self.assertIn(key, event)
            self.assertEqual(event["event"], "ui.input.read.begin")
            self.assertEqual(event["run_id"], "run-1")
            self.assertEqual(event["scope_id"], "repo-123")

    def test_recorder_writes_tty_context_and_anomaly_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DebugRecorderConfig(
                runtime_scope_dir=Path(tmpdir) / "scope",
                runtime_scope_id="repo-123",
                run_id="run-1",
                mode="deep",
                bundle_strict=True,
                capture_printable=False,
                ring_bytes=256,
                max_events=10,
                sample_rate=1,
            )
            recorder = DebugFlightRecorder(config)
            recorder.write_tty_context({"stdin_tty": True})
            recorder.append_tty_state_transition({"from": "raw", "to": "line"})
            recorder.append_anomaly({"event": "ui.anomaly.input_repeated_burst", "severity": "high"})

            tty_context = json.loads((recorder.session_dir / "tty_context.json").read_text(encoding="utf-8"))
            self.assertEqual(tty_context.get("stdin_tty"), True)
            transitions = (recorder.session_dir / "tty_state_transitions.jsonl").read_text(encoding="utf-8")
            self.assertIn('"from": "raw"', transitions)
            anomalies = (recorder.session_dir / "anomalies.jsonl").read_text(encoding="utf-8")
            self.assertIn("input_repeated_burst", anomalies)


if __name__ == "__main__":
    unittest.main()
