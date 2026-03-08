from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.ui.debug_flight_recorder import DebugFlightRecorder, DebugRecorderConfig


class DebugFlightRecorderLimitsTests(unittest.TestCase):
    def test_recorder_emits_limit_anomaly_and_stops_at_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = DebugRecorderConfig(
                runtime_scope_dir=Path(tmpdir) / "scope",
                runtime_scope_id="repo-123",
                run_id="run-2",
                mode="standard",
                bundle_strict=True,
                capture_printable=False,
                ring_bytes=128,
                max_events=1,
                sample_rate=1,
            )
            recorder = DebugFlightRecorder(config)
            recorder.record("ui.input.read.begin", component="test")
            recorder.record("ui.input.read.end", component="test")

            raw = recorder.events_path.read_text(encoding="utf-8").splitlines()
            events = [json.loads(line) for line in raw]
            event_names = [event["event"] for event in events]
            self.assertIn("ui.anomaly.debug_limit_reached", event_names)
            self.assertLessEqual(len(events), 2)


if __name__ == "__main__":
    unittest.main()
