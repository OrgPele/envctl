from __future__ import annotations

import unittest

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.ui.textual.app import (
    _dashboard_commands_help,
    _normalize_dashboard_command,
    _route_key_to_command_input,
    _to_renderable,
)
from envctl_engine.ui.textual.compat import normalize_text_edit_key_alias


class TextualDashboardRenderingSafetyTests(unittest.TestCase):
    def test_to_renderable_accepts_ansi_without_markup_failure(self) -> None:
        value = "\x1b[36m=== Dashboard ===\x1b[0m\n[1/1] Service ready"
        rendered = _to_renderable(value)

        self.assertIsNotNone(rendered)
        self.assertIn("=== Dashboard ===", rendered.plain)
        self.assertIn("[1/1] Service ready", rendered.plain)

    def test_dashboard_commands_help_includes_all_command_groups(self) -> None:
        text = _dashboard_commands_help()
        self.assertIn("Commands: (q)uit", text)
        self.assertIn("Lifecycle:", text)
        self.assertIn("Actions:", text)
        self.assertIn("Inspect:", text)
        self.assertNotIn("stop-all", text)
        self.assertNotIn("blast-all", text)
        self.assertNotIn("confi(g)", text)

    def test_normalize_dashboard_command_maps_shortcuts(self) -> None:
        self.assertEqual(_normalize_dashboard_command("r"), "restart")
        self.assertEqual(_normalize_dashboard_command("t"), "test")
        self.assertEqual(_normalize_dashboard_command("stopall"), "stop-all")
        self.assertEqual(_normalize_dashboard_command(""), "")

    def test_route_key_to_command_input_reroutes_printable_when_focus_drifted(self) -> None:
        consumed, value, request_focus, submit = _route_key_to_command_input(
            key="r",
            character="r",
            is_printable=True,
            focused_input=False,
            current_value="",
            dispatch_in_flight=False,
        )
        self.assertTrue(consumed)
        self.assertEqual(value, "r")
        self.assertTrue(request_focus)
        self.assertFalse(submit)

    def test_route_key_to_command_input_backspace_when_focus_drifted(self) -> None:
        consumed, value, request_focus, submit = _route_key_to_command_input(
            key="backspace",
            character=None,
            is_printable=False,
            focused_input=False,
            current_value="restart",
            dispatch_in_flight=False,
        )
        self.assertTrue(consumed)
        self.assertEqual(value, "restar")
        self.assertTrue(request_focus)
        self.assertFalse(submit)

    def test_route_key_to_command_input_shift_backspace_alias_when_focus_drifted(self) -> None:
        consumed, value, request_focus, submit = _route_key_to_command_input(
            key="shift+backspace",
            character=None,
            is_printable=False,
            focused_input=False,
            current_value="restart",
            dispatch_in_flight=False,
        )
        self.assertTrue(consumed)
        self.assertEqual(value, "restar")
        self.assertTrue(request_focus)
        self.assertFalse(submit)

    def test_route_key_to_command_input_modifier_backspace_alias_when_focus_drifted(self) -> None:
        consumed, value, request_focus, submit = _route_key_to_command_input(
            key="ctrl+shift+backspace",
            character=None,
            is_printable=False,
            focused_input=False,
            current_value="restart",
            dispatch_in_flight=False,
        )
        self.assertTrue(consumed)
        self.assertEqual(value, "restar")
        self.assertTrue(request_focus)
        self.assertFalse(submit)

    def test_route_key_to_command_input_modifier_delete_alias_when_focus_drifted(self) -> None:
        consumed, value, request_focus, submit = _route_key_to_command_input(
            key="alt+delete",
            character=None,
            is_printable=False,
            focused_input=False,
            current_value="restart",
            dispatch_in_flight=False,
        )
        self.assertTrue(consumed)
        self.assertEqual(value, "restar")
        self.assertTrue(request_focus)
        self.assertFalse(submit)

    def test_normalize_text_edit_key_alias_uses_character_fallback(self) -> None:
        self.assertEqual(normalize_text_edit_key_alias("unknown", character="\x7f"), "backspace")

    def test_route_key_to_command_input_enter_requests_submit_when_value_exists(self) -> None:
        consumed, value, request_focus, submit = _route_key_to_command_input(
            key="enter",
            character=None,
            is_printable=False,
            focused_input=False,
            current_value="r",
            dispatch_in_flight=False,
        )
        self.assertTrue(consumed)
        self.assertEqual(value, "r")
        self.assertTrue(request_focus)
        self.assertTrue(submit)


if __name__ == "__main__":
    unittest.main()
