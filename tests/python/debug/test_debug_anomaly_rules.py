from __future__ import annotations

import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.ui.debug_anomaly_rules import detect_input_anomalies


class DebugAnomalyRulesTests(unittest.TestCase):
    def test_detect_repeated_burst(self) -> None:
        anomalies = detect_input_anomalies(raw="rrrrrr", sanitized="rrrrrr", backend="fallback")
        self.assertTrue(any(a.get("event") == "ui.anomaly.input_repeated_burst" for a in anomalies))

    def test_detect_empty_submit_with_bytes(self) -> None:
        anomalies = detect_input_anomalies(raw="\r", sanitized="", backend="fallback", bytes_read=1)
        self.assertTrue(any(a.get("event") == "ui.anomaly.empty_submit_with_bytes" for a in anomalies))


if __name__ == "__main__":
    unittest.main()
