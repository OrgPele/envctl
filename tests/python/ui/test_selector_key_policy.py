from __future__ import annotations

import unittest

from envctl_engine.ui.textual.screens.selector.textual_key_policy import (
    SelectorFilterKeyDecision,
    SelectorKeyDecision,
    emit_selector_key_trace,
    resolve_selector_filter_key,
    resolve_selector_key,
)


class SelectorKeyPolicyTests(unittest.TestCase):
    def test_top_level_policy_handles_focus_and_submit_shortcuts(self) -> None:
        self.assertEqual(resolve_selector_key("tab", filter_focused=False), SelectorKeyDecision.CYCLE_FOCUS)
        self.assertEqual(resolve_selector_key("enter", filter_focused=True), SelectorKeyDecision.SUBMIT)
        self.assertEqual(resolve_selector_key("enter", filter_focused=False), SelectorKeyDecision.SUBMIT)
        self.assertEqual(resolve_selector_key("slash", filter_focused=False), SelectorKeyDecision.FOCUS_FILTER)

    def test_top_level_policy_preserves_filter_text_editing(self) -> None:
        self.assertEqual(resolve_selector_key("slash", filter_focused=True), SelectorKeyDecision.NOOP)
        self.assertEqual(resolve_selector_key("a", filter_focused=True), SelectorKeyDecision.NOOP)
        self.assertEqual(resolve_selector_key("up", filter_focused=False), SelectorKeyDecision.NOOP)

    def test_filter_policy_recovers_navigation_keys_to_list(self) -> None:
        for key in ("up", "k", "w"):
            with self.subTest(key=key):
                self.assertEqual(resolve_selector_filter_key(key), SelectorFilterKeyDecision.NAV_UP)
        for key in ("down", "j", "s"):
            with self.subTest(key=key):
                self.assertEqual(resolve_selector_filter_key(key), SelectorFilterKeyDecision.NAV_DOWN)
        self.assertEqual(resolve_selector_filter_key("space"), SelectorFilterKeyDecision.TOGGLE)

    def test_filter_policy_ignores_text_editing_keys(self) -> None:
        for key in ("left", "right", "backspace", "a", "slash"):
            with self.subTest(key=key):
                self.assertEqual(resolve_selector_filter_key(key), SelectorFilterKeyDecision.NOOP)

    def test_key_trace_emits_standard_selector_debug_payload(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []

        emit_selector_key_trace(
            emit=lambda event, **payload: events.append((event, payload)),
            deep_debug=True,
            selector_id="selector-1",
            key="tab",
            focused_widget_id="selector-list",
            list_index_before=1,
            list_index_after=2,
            handled=True,
        )

        self.assertEqual(events[0][0], "ui.selector.key")
        self.assertEqual(events[0][1]["component"], "ui.textual.selector")
        self.assertEqual(events[0][1]["selector_id"], "selector-1")
        self.assertEqual(events[0][1]["key"], "tab")
        self.assertEqual(events[0][1]["list_index_before"], 1)
        self.assertEqual(events[0][1]["list_index_after"], 2)
        self.assertTrue(events[0][1]["handled"])


if __name__ == "__main__":
    unittest.main()
