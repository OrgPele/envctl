from __future__ import annotations

import unittest

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.ui.status_symbols import (  # noqa: E402
    STATUS_FAILURE,
    STATUS_NEUTRAL,
    STATUS_SIMULATED,
    STATUS_STARTING,
    STATUS_SUCCESS,
    dependency_status_badge,
    final_status_symbol,
    health_status_badge,
    health_status_icon,
    health_status_severity,
    service_status_badge,
)


class StatusSymbolsTests(unittest.TestCase):
    def test_service_status_mapping_uses_consistent_terminal_glyphs(self) -> None:
        cases = {
            "running": (STATUS_SUCCESS, "success", "Running"),
            "healthy": (STATUS_SUCCESS, "success", "Healthy"),
            "simulated": (STATUS_SIMULATED, "warning", "Simulated"),
            "starting": (STATUS_STARTING, "warning", "Starting"),
            "unknown": (STATUS_STARTING, "warning", "Unknown"),
            "stale": (STATUS_FAILURE, "failure", "Stale"),
            "unreachable": (STATUS_FAILURE, "failure", "Unreachable"),
            "stopped": (STATUS_NEUTRAL, "neutral", "Not running"),
            "failed": (STATUS_FAILURE, "failure", "failed"),
        }

        for status, expected in cases.items():
            with self.subTest(status=status):
                badge = service_status_badge(status)
                self.assertEqual((badge.symbol, badge.severity, badge.label), expected)

    def test_dependency_status_mapping_uses_failure_for_bad_states_only(self) -> None:
        self.assertEqual(dependency_status_badge("healthy").symbol, STATUS_SUCCESS)
        self.assertEqual(dependency_status_badge("simulated").symbol, STATUS_SIMULATED)
        self.assertEqual(dependency_status_badge("starting").symbol, STATUS_STARTING)
        self.assertEqual(dependency_status_badge("unhealthy").symbol, STATUS_FAILURE)
        self.assertEqual(dependency_status_badge("unreachable").symbol, STATUS_FAILURE)
        self.assertEqual(dependency_status_badge("custom-error").symbol, STATUS_FAILURE)
        self.assertEqual(dependency_status_badge("", success=True).symbol, STATUS_SUCCESS)
        self.assertEqual(dependency_status_badge("", failure_count=0).symbol, STATUS_STARTING)
        self.assertEqual(dependency_status_badge("", failure_count=2).symbol, STATUS_FAILURE)

    def test_health_status_mapping_decouples_counts_from_rendered_glyphs(self) -> None:
        self.assertEqual(health_status_badge("running").symbol, STATUS_SUCCESS)
        self.assertEqual(health_status_badge("simulated").symbol, STATUS_SIMULATED)
        self.assertEqual(health_status_badge("starting").symbol, STATUS_STARTING)
        self.assertEqual(health_status_badge("stopped").symbol, STATUS_NEUTRAL)
        self.assertEqual(health_status_badge("unreachable").symbol, STATUS_FAILURE)
        self.assertEqual(health_status_icon("failed"), STATUS_FAILURE)

        self.assertEqual(health_status_severity("healthy"), "ok")
        self.assertEqual(health_status_severity("unknown"), "warn")
        self.assertEqual(health_status_severity("stopped"), "warn")
        self.assertEqual(health_status_severity("failed"), "bad")

    def test_final_status_symbol_uses_canonical_success_and_failure_glyphs(self) -> None:
        self.assertEqual(final_status_symbol(True), STATUS_SUCCESS)
        self.assertEqual(final_status_symbol(False), STATUS_FAILURE)


if __name__ == "__main__":
    unittest.main()
