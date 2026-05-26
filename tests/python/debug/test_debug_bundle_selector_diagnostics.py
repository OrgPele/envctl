from __future__ import annotations

import unittest

from envctl_engine.debug.debug_bundle_selector_diagnostics import analyze_selector_diagnostics


class DebugBundleSelectorDiagnosticsTests(unittest.TestCase):
    def test_selector_diagnostics_detect_pipeline_and_focus_gaps(self) -> None:
        timeline = [
            {"event": "ui.selector.lifecycle", "selector_id": "Projects", "phase": "enter", "ts_mono_ns": 0},
            {
                "event": "ui.selector.key.driver.summary",
                "selector_id": "Projects",
                "key_events_total": 5,
                "key_events_by_name": {"Down": 5},
                "read_bytes": 30,
                "escape_bytes": 12,
                "non_key_messages": {"AppBlur": 1},
            },
            {
                "event": "ui.selector.key.summary",
                "selector_id": "Projects",
                "event_counts": {"Down": 2},
                "handled_counts": {"Down": 2},
            },
            {
                "event": "ui.selector.key.idle_after_activity",
                "selector_id": "Projects",
                "idle_ms": 3000,
                "nav_event_counter": 2,
                "focused_widget_id": "selector-list",
            },
            {"event": "heartbeat", "ts_mono_ns": 3_000_000_000},
        ]

        diagnostics = analyze_selector_diagnostics(timeline)

        self.assertEqual(diagnostics.low_throughput, [])
        self.assertEqual(
            diagnostics.key_pipeline_gaps,
            [
                {
                    "selector": "id:projects",
                    "driver_key_events": 5,
                    "app_key_events": 2,
                    "dropped_after_driver": 3,
                    "driver_key_names": {"Down": 5},
                }
            ],
        )
        self.assertEqual(diagnostics.read_pipeline_gaps, [])
        self.assertEqual(
            diagnostics.driver_focus_loss,
            [{"selector": "id:projects", "app_blur_events": 1, "app_focus_events": 0}],
        )
        self.assertEqual(
            diagnostics.idle_after_activity,
            [
                {
                    "selector": "id:projects",
                    "idle_ms": 3000,
                    "nav_event_counter": 2,
                    "focused_widget_id": "selector-list",
                }
            ],
        )

    def test_selector_diagnostics_detect_inactivity_low_throughput_and_double_toggle(self) -> None:
        timeline = [
            {"event": "ui.selector.lifecycle", "prompt": "Pick", "phase": "enter", "ts_mono_ns": 0},
            {"event": "ui.selector.mouse", "prompt": "Other", "row_id": "row-1", "ts_mono_ns": 100},
            {"event": "ui.selector.mouse", "prompt": "Other", "row_id": "row-1", "ts_mono_ns": 100_000_000},
            {"event": "ui.selector.submit", "prompt": "Other", "blocked": True},
            {"event": "ui.selector.submit", "prompt": "Other", "cancelled": True},
            {"event": "heartbeat", "ts_mono_ns": 3_000_000_000},
        ]

        diagnostics = analyze_selector_diagnostics(timeline)

        self.assertEqual(diagnostics.inactive_tokens, ["prompt:pick"])
        self.assertEqual(
            diagnostics.low_throughput,
            [{"selector": "prompt:pick", "observed_window_ms": 3000.0, "key_events": 0}],
        )
        self.assertTrue(diagnostics.mouse_double_toggle)
        self.assertTrue(diagnostics.blocked_then_cancel)


if __name__ == "__main__":
    unittest.main()
