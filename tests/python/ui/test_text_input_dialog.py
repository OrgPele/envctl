from __future__ import annotations

import importlib.util
import unittest

from envctl_engine.ui.textual.screens.text_input_dialog import run_text_input_dialog_textual


class TextInputDialogTests(unittest.IsolatedAsyncioTestCase):
    async def test_enter_on_empty_text_area_uses_default_action(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        app = run_text_input_dialog_textual(
            title="PR Message",
            help_text="PR message (leave blank to use default).",
            placeholder="Type a PR message",
            default_button_label="Use MAIN_TASK.md",
            build_only=True,
        )

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.return_value, "")

