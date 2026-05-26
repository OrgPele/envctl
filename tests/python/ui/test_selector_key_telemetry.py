from __future__ import annotations

import time
import unittest

from envctl_engine.ui.textual.screens.selector.textual_key_telemetry import SelectorKeyTelemetry


class SelectorKeyTelemetryTests(unittest.TestCase):
    def test_records_counts_only_when_enabled(self) -> None:
        disabled = SelectorKeyTelemetry(enabled=False)
        disabled.record_raw_key("down")
        disabled.record_event_key("down")
        disabled.record_handled_key("down")
        self.assertEqual(disabled.raw_counts, {})
        self.assertEqual(disabled.event_counts, {})
        self.assertEqual(disabled.handled_counts, {})

        telemetry = SelectorKeyTelemetry(enabled=True)
        telemetry.record_raw_key("down")
        telemetry.record_raw_key("down")
        telemetry.record_event_key("down")
        telemetry.record_handled_key("enter")

        self.assertEqual(telemetry.raw_counts, {"down": 2})
        self.assertEqual(telemetry.event_counts, {"down": 1})
        self.assertEqual(telemetry.handled_counts, {"enter": 1})

    def test_snapshot_emits_counts_idle_and_driver_details(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []

        def emit(event: str, **payload: object) -> None:
            events.append((event, dict(payload)))

        telemetry = SelectorKeyTelemetry(enabled=True)
        telemetry.record_raw_key("down")
        telemetry.record_event_key("down")
        telemetry.record_handled_key("down")
        telemetry.mark_navigation("down", now_ns=time.monotonic_ns() - 3_000_000_000)

        telemetry.emit_snapshot(
            emit=emit,
            deep_debug=True,
            selector_id="restart",
            focused_widget_id="selector-list",
            list_index=1,
            driver_snapshot=lambda: {"read_calls": 4, "read_bytes": 12},
            thread_snapshot=lambda: {"input_thread_alive": True},
            now_ns=time.monotonic_ns(),
        )
        telemetry.emit_snapshot(
            emit=emit,
            deep_debug=True,
            selector_id="restart",
            focused_widget_id="selector-list",
            list_index=1,
            driver_snapshot=lambda: {"read_calls": 4, "read_bytes": 12},
            thread_snapshot=lambda: {"input_thread_alive": True},
            now_ns=time.monotonic_ns(),
        )

        event_names = [event for event, _payload in events]
        self.assertIn("ui.selector.key.snapshot", event_names)
        self.assertIn("ui.selector.key.idle_after_activity", event_names)
        self.assertIn("ui.selector.key.driver.snapshot", event_names)
        self.assertIn("ui.selector.key.driver.idle_after_activity", event_names)
        driver_idle = [payload for event, payload in events if event == "ui.selector.key.driver.idle_after_activity"]
        self.assertEqual(driver_idle[-1]["read_calls"], 4)
        self.assertEqual(driver_idle[-1]["input_thread_alive"], True)

    def test_summary_emits_counts_and_final_thread_snapshot(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []

        def emit(event: str, **payload: object) -> None:
            events.append((event, dict(payload)))

        telemetry = SelectorKeyTelemetry(enabled=True)
        telemetry.record_event_key("enter")
        telemetry.record_handled_key("enter")

        telemetry.emit_summary(
            emit=emit,
            deep_debug=True,
            selector_id="restart",
            thread_snapshot=lambda: {"input_thread_alive": False},
        )

        self.assertEqual(events[0][0], "ui.selector.key.summary")
        self.assertEqual(events[0][1]["event_counts"], {"enter": 1})
        self.assertEqual(events[1][0], "ui.selector.key.driver.thread.final")
        self.assertEqual(events[1][1]["input_thread_alive"], False)


if __name__ == "__main__":
    unittest.main()
