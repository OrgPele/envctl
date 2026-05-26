from __future__ import annotations

import unittest

from envctl_engine.ui.textual.screens.selector.textual_app_runtime import (
    SelectorEventController,
    SelectorFocusController,
    SelectorStatusController,
    SelectorStatusPresenter,
)


class SelectorStatusPresenterTests(unittest.TestCase):
    def test_status_text_includes_counts_focus_and_debug_navigation(self) -> None:
        presenter = SelectorStatusPresenter()

        status = presenter.status_text(
            visible_count=3,
            selected_count=1,
            total_count=4,
            focused_view_index=1,
            focused_label="Beta Backend",
            focusable_count=3,
            deep_debug=True,
            nav_event_counter=7,
            last_nav_key="down",
            edge_hint="bottom boundary",
        )

        self.assertEqual(
            status,
            "1 selected • 3 visible • 4 total • focus: 2/3 Beta Backend • key#7:down • bottom boundary",
        )

    def test_error_message_overrides_status_until_cleared(self) -> None:
        presenter = SelectorStatusPresenter()

        presenter.show_error("No items were selected.")
        self.assertEqual(
            presenter.status_text(
                visible_count=3,
                selected_count=0,
                total_count=3,
                focused_view_index=None,
                focused_label=None,
                focusable_count=0,
                deep_debug=False,
                nav_event_counter=0,
                last_nav_key="",
                edge_hint="",
            ),
            "No items were selected.",
        )

        self.assertTrue(presenter.clear_error())
        self.assertFalse(presenter.has_error)
        self.assertFalse(presenter.clear_error())


class SelectorStatusControllerTests(unittest.TestCase):
    def test_status_controller_owns_error_timer_lifecycle(self) -> None:
        callbacks: list[object] = []
        stopped: list[object] = []
        sync_calls = 0

        class _Timer:
            def stop(self) -> None:
                stopped.append(self)

        def set_timer(seconds: float, callback: object) -> object:
            self.assertEqual(seconds, 3.0)
            callbacks.append(callback)
            return _Timer()

        def sync_status() -> None:
            nonlocal sync_calls
            sync_calls += 1

        controller = SelectorStatusController(timeout_seconds=3.0, set_timer=set_timer, sync_status=sync_status)

        controller.show_error("No items were selected.")
        self.assertTrue(controller.has_error)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(sync_calls, 1)

        controller.touch_timeout()
        self.assertEqual(len(callbacks), 2)
        self.assertEqual(len(stopped), 1)

        controller.clear_error()
        self.assertFalse(controller.has_error)
        self.assertEqual(len(stopped), 2)
        self.assertEqual(sync_calls, 2)

        controller.clear_error()
        self.assertEqual(sync_calls, 2)

    def test_status_controller_delegates_status_text_to_presenter(self) -> None:
        controller = SelectorStatusController(timeout_seconds=1.0, set_timer=lambda _seconds, _callback: object())
        self.assertEqual(
            controller.status_text(
                visible_count=1,
                selected_count=0,
                total_count=2,
                focused_view_index=None,
                focused_label=None,
                focusable_count=0,
                deep_debug=False,
                nav_event_counter=0,
                last_nav_key="",
                edge_hint="",
            ),
            "0 selected • 1 visible • 2 total • focus: -",
        )


class SelectorFocusControllerTests(unittest.TestCase):
    def test_widget_id_prefers_focused_id_then_known_focus_targets(self) -> None:
        controller = SelectorFocusController(emit=None, deep_debug=False, selector_id="restart")

        focused = type("Focused", (), {"id": "btn-run"})()

        self.assertEqual(controller.widget_id(focused=focused, list_has_focus=False, filter_has_focus=False), "btn-run")
        self.assertEqual(controller.widget_id(focused=None, list_has_focus=True, filter_has_focus=False), "selector-list")
        self.assertEqual(
            controller.widget_id(focused=None, list_has_focus=False, filter_has_focus=True),
            "selector-filter",
        )
        self.assertEqual(controller.widget_id(focused=None, list_has_focus=False, filter_has_focus=False), "unknown")

    def test_focus_order_includes_run_button_only_when_enabled(self) -> None:
        controller = SelectorFocusController(emit=None, deep_debug=False, selector_id="restart")

        self.assertEqual(
            controller.focus_order(run_enabled=False),
            ("selector-filter", "selector-list", "btn-cancel"),
        )
        self.assertEqual(
            controller.focus_order(run_enabled=True),
            ("selector-filter", "selector-list", "btn-cancel", "btn-run"),
        )

    def test_focus_events_emit_only_on_change(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        controller = SelectorFocusController(
            emit=lambda event, **payload: events.append((event, payload)),
            deep_debug=True,
            selector_id="restart",
        )

        controller.emit_focus(reason="mount", current_widget_id="selector-list")
        controller.emit_focus(reason="mount_repeat", current_widget_id="selector-list")
        controller.emit_focus(reason="tab", current_widget_id="btn-run")

        self.assertEqual([event for event, _payload in events], ["ui.selector.focus", "ui.selector.focus"])
        self.assertEqual(events[0][1]["from_widget_id"], "unknown")
        self.assertEqual(events[0][1]["to_widget_id"], "selector-list")
        self.assertEqual(events[1][1]["from_widget_id"], "selector-list")
        self.assertEqual(events[1][1]["to_widget_id"], "btn-run")


class SelectorEventControllerTests(unittest.TestCase):
    def test_submit_cancel_and_exit_events_keep_public_and_debug_payloads_together(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        controller = SelectorEventController(
            emit=lambda event, **payload: events.append((event, payload)),
            deep_debug=True,
            selector_id="restart",
            prompt="Restart services",
            option_count=4,
            multi=True,
        )

        controller.submit_blocked(cause="enter")
        controller.submit_confirmed(selected_count=2, cause="button_run")
        controller.cancel(cause="escape")
        controller.exit()

        event_names = [event for event, _payload in events]
        self.assertEqual(
            event_names,
            [
                "ui.selection.confirm",
                "ui.selector.submit",
                "ui.selection.confirm",
                "ui.selector.submit",
                "ui.selection.cancel",
                "ui.selector.submit",
                "ui.screen.exit",
                "ui.selector.lifecycle",
            ],
        )
        self.assertEqual(events[0][1]["blocked"], True)
        self.assertEqual(events[1][1]["blocked"], True)
        self.assertEqual(events[3][1]["selected_count"], 2)
        self.assertEqual(events[5][1]["cancelled"], True)
        self.assertEqual(events[7][1]["phase"], "exit")


if __name__ == "__main__":
    unittest.main()
