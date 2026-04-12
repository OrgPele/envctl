from __future__ import annotations

import unittest
from unittest.mock import patch
import importlib
from types import SimpleNamespace
from contextlib import redirect_stdout
from io import StringIO

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"

menu_module = importlib.import_module("envctl_engine.ui.menu")
FallbackMenuPresenter = menu_module.FallbackMenuPresenter
MenuOption = menu_module.MenuOption
build_menu_presenter = menu_module.build_menu_presenter
PromptToolkitMenuPresenter = menu_module.PromptToolkitMenuPresenter


class InteractiveMenuTests(unittest.TestCase):
    def test_build_menu_presenter_uses_prompt_toolkit_when_available(self) -> None:
        with (
            patch("envctl_engine.ui.menu.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.menu.prompt_toolkit_available", return_value=True),
        ):
            presenter = build_menu_presenter({})
        self.assertIsInstance(presenter, PromptToolkitMenuPresenter)

    def test_build_menu_presenter_uses_fallback_when_prompt_toolkit_disabled(self) -> None:
        with (
            patch("envctl_engine.ui.menu.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.menu.prompt_toolkit_available", return_value=True),
        ):
            presenter = build_menu_presenter({"ENVCTL_UI_PROMPT_TOOLKIT": "false"})
        self.assertIsInstance(presenter, FallbackMenuPresenter)

    def test_build_menu_presenter_uses_fallback_when_non_interactive(self) -> None:
        with patch("envctl_engine.ui.menu.can_interactive_tty", return_value=False):
            presenter = build_menu_presenter({})
        self.assertIsInstance(presenter, FallbackMenuPresenter)

    def test_prompt_toolkit_presenter_ctrl_c_returns_none(self) -> None:
        presenter = PromptToolkitMenuPresenter()

        class _Dialog:
            def run(self):
                raise KeyboardInterrupt

        shortcuts = SimpleNamespace(
            radiolist_dialog=lambda **_kwargs: _Dialog(),
            checkboxlist_dialog=lambda **_kwargs: _Dialog(),
        )

        def _import(name: str):
            if name == "prompt_toolkit.shortcuts":
                return shortcuts
            raise AssertionError(name)

        with (
            patch("envctl_engine.ui.menu.importlib.import_module", side_effect=_import),
            patch.object(PromptToolkitMenuPresenter, "_dialog_style", return_value=None),
        ):
            self.assertIsNone(presenter.select_single("Pick", [MenuOption("A", "a")]))
            self.assertIsNone(presenter.select_multi("Pick", [MenuOption("A", "a")]))

    def test_fallback_menu_reprompts_after_empty_input(self) -> None:
        answers = iter(["", "2"])
        prompts: list[str] = []

        def provider(prompt: str) -> str:
            prompts.append(prompt)
            return next(answers)

        presenter = FallbackMenuPresenter(input_provider=provider)
        with redirect_stdout(StringIO()):
            selected = presenter.select_single(
                "Restart",
                [MenuOption("Main Backend", "backend"), MenuOption("Main Frontend", "frontend")],
            )

        self.assertEqual(selected, "frontend")
        self.assertEqual(len(prompts), 2)

    def test_fallback_menu_reprompts_after_invalid_selection(self) -> None:
        answers = iter(["99", "1,2"])
        presenter = FallbackMenuPresenter(input_provider=lambda _prompt: next(answers))

        with redirect_stdout(StringIO()):
            selected = presenter.select_multi(
                "Restart",
                [MenuOption("Main Backend", "backend"), MenuOption("Main Frontend", "frontend")],
            )

        self.assertEqual(selected, ["backend", "frontend"])


if __name__ == "__main__":
    unittest.main()
