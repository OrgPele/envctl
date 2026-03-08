from __future__ import annotations

import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.debug.debug_contract import apply_debug_event_contract, DEBUG_EVENT_SCHEMA_VERSION


class DebugEventContractTests(unittest.TestCase):
    def test_apply_contract_sets_required_fields(self) -> None:
        base = apply_debug_event_contract(
            event_name="ui.input.submit",
            payload={"command_id": "cmd-1"},
            timestamp="2026-03-02T10:00:00+00:00",
            trace_id="trace-1",
        )
        self.assertEqual(base["event"], "ui.input.submit")
        self.assertEqual(base["command_id"], "cmd-1")
        self.assertEqual(base["trace_id"], "trace-1")
        self.assertEqual(base["schema_version"], DEBUG_EVENT_SCHEMA_VERSION)
        self.assertIn("phase", base)

    def test_apply_contract_sets_phase_for_dispatch_event(self) -> None:
        base = apply_debug_event_contract(
            event_name="ui.input.dispatch.begin",
            payload={},
            timestamp="2026-03-02T10:00:00+00:00",
            trace_id="trace-1",
        )
        self.assertEqual(base["phase"], "dispatch")

    def test_apply_contract_sets_phase_for_process_launch_event(self) -> None:
        base = apply_debug_event_contract(
            event_name="process.launch",
            payload={"launch_intent": "background_service"},
            timestamp="2026-03-02T10:00:00+00:00",
            trace_id="trace-1",
        )
        self.assertEqual(base["phase"], "lifecycle")


if __name__ == "__main__":
    unittest.main()
