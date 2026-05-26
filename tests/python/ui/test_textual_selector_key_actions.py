from __future__ import annotations

import unittest

from envctl_engine.ui.textual.screens.selector.textual_key_telemetry import SelectorKeyTelemetry


class _Event:
    def __init__(self, key: str) -> None:
        self.key = key
        self.stopped = False
        self.prevented = False

    def stop(self) -> None:
        self.stopped = True

    def prevent_default(self) -> None:
        self.prevented = True


class _Input:
    def __init__(self, *, value: str = "", has_focus: bool = False) -> None:
        self.value = value
        self.has_focus = has_focus


class SelectorKeyActionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_enter_submits_and_emits_handled_trace(self) -> None:
        from envctl_engine.ui.textual.screens.selector.textual_app_key_actions import SelectorKeyActions

        event = _Event("enter")
        submitted: list[str] = []
        traces: list[dict[str, object]] = []
        suppressed: list[bool] = []

        actions = SelectorKeyActions(
            key_telemetry=SelectorKeyTelemetry(enabled=True),
            key_trace_verbose=True,
            trace_key=lambda **payload: traces.append(dict(payload)),
            focused_widget_id=lambda: "selector-list",
            list_index=lambda: 2,
            filter_input=lambda: _Input(),
            handle_text_edit_key_alias=lambda *, widget, event: False,
            cycle_focus=lambda: None,
            submit=lambda *, cause: _completed(submitted, cause),
            focus_filter=lambda *, reason: None,
            focus_list=lambda *, reason: None,
            nav_up=lambda: _completed(submitted, "nav_up"),
            nav_down=lambda: _completed(submitted, "nav_down"),
            toggle=lambda: _completed(submitted, "toggle"),
            suppress_list_selected_once=lambda value: suppressed.append(value),
        )

        await actions.handle_key(event)

        self.assertTrue(event.stopped)
        self.assertTrue(event.prevented)
        self.assertEqual(submitted, ["enter_key"])
        self.assertEqual(suppressed, [True])
        self.assertEqual(traces[-1]["key"], "enter")
        self.assertEqual(traces[-1]["handled"], True)
        self.assertEqual(traces[-1]["list_index_before"], 2)

    async def test_slash_focuses_filter_and_clears_previous_query(self) -> None:
        from envctl_engine.ui.textual.screens.selector.textual_app_key_actions import SelectorKeyActions

        event = _Event("slash")
        filter_input = _Input(value="abc")
        focus_reasons: list[str] = []

        actions = SelectorKeyActions(
            key_telemetry=SelectorKeyTelemetry(enabled=False),
            key_trace_verbose=False,
            trace_key=lambda **_payload: None,
            focused_widget_id=lambda: "selector-list",
            list_index=lambda: 0,
            filter_input=lambda: filter_input,
            handle_text_edit_key_alias=lambda *, widget, event: False,
            cycle_focus=lambda: None,
            submit=lambda *, cause: _completed(focus_reasons, cause),
            focus_filter=lambda *, reason: focus_reasons.append(reason),
            focus_list=lambda *, reason: None,
            nav_up=lambda: _completed(focus_reasons, "nav_up"),
            nav_down=lambda: _completed(focus_reasons, "nav_down"),
            toggle=lambda: _completed(focus_reasons, "toggle"),
            suppress_list_selected_once=lambda _value: None,
        )

        await actions.handle_key(event)

        self.assertTrue(event.stopped)
        self.assertTrue(event.prevented)
        self.assertEqual(filter_input.value, "")
        self.assertEqual(focus_reasons, ["slash_focus_filter"])

    async def test_filter_focused_navigation_recovers_list_before_moving(self) -> None:
        from envctl_engine.ui.textual.screens.selector.textual_app_key_actions import SelectorKeyActions

        event = _Event("down")
        calls: list[str] = []

        actions = SelectorKeyActions(
            key_telemetry=SelectorKeyTelemetry(enabled=False),
            key_trace_verbose=False,
            trace_key=lambda **_payload: None,
            focused_widget_id=lambda: "selector-filter",
            list_index=lambda: 0,
            filter_input=lambda: _Input(has_focus=True),
            handle_text_edit_key_alias=lambda *, widget, event: False,
            cycle_focus=lambda: calls.append("cycle"),
            submit=lambda *, cause: _completed(calls, cause),
            focus_filter=lambda *, reason: calls.append(reason),
            focus_list=lambda *, reason: calls.append(reason),
            nav_up=lambda: _completed(calls, "nav_up"),
            nav_down=lambda: _completed(calls, "nav_down"),
            toggle=lambda: _completed(calls, "toggle"),
            suppress_list_selected_once=lambda _value: None,
        )

        handled = await actions.handle_filter_focus_key(event)

        self.assertTrue(handled)
        self.assertTrue(event.stopped)
        self.assertTrue(event.prevented)
        self.assertEqual(calls, ["filter_key_recover", "nav_down"])

    def test_record_event_key_emits_verbose_unhandled_trace(self) -> None:
        from envctl_engine.ui.textual.screens.selector.textual_app_key_actions import SelectorKeyActions

        traces: list[dict[str, object]] = []
        actions = SelectorKeyActions(
            key_telemetry=SelectorKeyTelemetry(enabled=True),
            key_trace_verbose=True,
            trace_key=lambda **payload: traces.append(dict(payload)),
            focused_widget_id=lambda: "selector-list",
            list_index=lambda: 4,
            filter_input=lambda: _Input(),
            handle_text_edit_key_alias=lambda *, widget, event: False,
            cycle_focus=lambda: None,
            submit=lambda *, cause: _completed([], cause),
            focus_filter=lambda *, reason: None,
            focus_list=lambda *, reason: None,
            nav_up=lambda: _completed([], "nav_up"),
            nav_down=lambda: _completed([], "nav_down"),
            toggle=lambda: _completed([], "toggle"),
            suppress_list_selected_once=lambda _value: None,
        )

        actions.record_event_key(_Event("x"))

        self.assertEqual(traces, [
            {
                "event": "ui.selector.key.event",
                "key": "x",
                "focused_widget_id": "selector-list",
                "list_index_before": 4,
                "list_index_after": 4,
                "handled": False,
            }
        ])


async def _completed(target: list[str], value: str) -> None:
    target.append(value)


if __name__ == "__main__":
    unittest.main()
