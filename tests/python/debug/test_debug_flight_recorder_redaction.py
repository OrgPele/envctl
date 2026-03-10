from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.debug.debug_bundle import sanitize_runtime_event


class DebugFlightRecorderRedactionTests(unittest.TestCase):
    def test_ui_input_submit_is_hashed(self) -> None:
        event = {"event": "ui.input.submit", "command": "token=secret-value"}
        sanitized = sanitize_runtime_event(event, salt="test-salt")
        self.assertNotIn("command", sanitized)
        self.assertIn("command_hash", sanitized)
        self.assertIn("command_length", sanitized)

    def test_planning_selection_invalid_is_scrubbed(self) -> None:
        event = {"event": "planning.selection.invalid", "selection": "PASSWORD=abc"}
        sanitized = sanitize_runtime_event(event, salt="test-salt")
        self.assertNotIn("selection", sanitized)
        self.assertIn("selection_hash", sanitized)

    def test_error_fields_are_redacted(self) -> None:
        event = {"event": "startup.failed", "error": "TOKEN=abc123"}
        sanitized = sanitize_runtime_event(event, salt="test-salt")
        self.assertIn("error", sanitized)
        self.assertNotIn("abc123", str(sanitized["error"]))


if __name__ == "__main__":
    unittest.main()
