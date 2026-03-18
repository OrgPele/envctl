from __future__ import annotations

import importlib.util
import unittest

from envctl_engine.ui.textual.screens.text_input_dialog import run_text_input_dialog_textual


class TextInputDialogTests(unittest.IsolatedAsyncioTestCase):
    async def test_space_inserts_literal_space_into_text_area(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        app = run_text_input_dialog_textual(
            title="Commit Message",
            help_text="Commit message (leave blank to use the envctl commit log).",
            placeholder="Type a commit message",
            default_button_label="Use envctl commit log",
            build_only=True,
        )

        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.press("space")
            await pilot.press("b")
            await pilot.pause()
            text_area = app.query_one("#dialog-input")
            self.assertEqual(getattr(text_area, "text", None), "a b")

    async def test_shift_backspace_deletes_like_backspace(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        app = run_text_input_dialog_textual(
            title="Commit Message",
            help_text="Commit message (leave blank to use the envctl commit log).",
            placeholder="Type a commit message",
            default_button_label="Use envctl commit log",
            build_only=True,
        )

        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.press("b")
            await pilot.press("shift+backspace")
            await pilot.pause()
            text_area = app.query_one("#dialog-input")
            self.assertEqual(getattr(text_area, "text", None), "a")

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
