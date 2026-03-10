from __future__ import annotations

import os
import importlib
import termios
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"

menu_module = importlib.import_module("envctl_engine.ui.menu")
terminal_session = importlib.import_module("envctl_engine.ui.terminal_session")
terminal_ui_module = importlib.import_module("envctl_engine.ui.dashboard.terminal_ui")

PromptToolkitMenuPresenter = menu_module.PromptToolkitMenuPresenter
build_menu_presenter = menu_module.build_menu_presenter
TerminalSession = terminal_session.TerminalSession
RuntimeTerminalUI = terminal_ui_module.RuntimeTerminalUI


class PromptToolkitDefaultTests(unittest.TestCase):
    def test_terminal_ui_import_has_no_cycle(self) -> None:
        command = (
            "import sys; "
            f"sys.path.insert(0, {str(PYTHON_ROOT)!r}); "
            "from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI; "
            "print(RuntimeTerminalUI.__name__)"
        )
        completed = subprocess.run(
            [sys.executable, "-c", command],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        self.assertIn("RuntimeTerminalUI", completed.stdout)

    def test_menu_presenter_uses_prompt_toolkit_when_enabled(self) -> None:
        with (
            patch("envctl_engine.ui.menu.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.menu.prompt_toolkit_available", return_value=True),
        ):
            presenter = build_menu_presenter({})

        self.assertIsInstance(presenter, PromptToolkitMenuPresenter)

    def test_menu_presenter_uses_fallback_when_prompt_toolkit_disabled(self) -> None:
        with (
            patch("envctl_engine.ui.menu.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.menu.prompt_toolkit_available", return_value=True),
        ):
            presenter = build_menu_presenter({"ENVCTL_UI_PROMPT_TOOLKIT": "false"})

        self.assertIsInstance(presenter, menu_module.FallbackMenuPresenter)

    def test_menu_presenter_emits_backend_choice(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []

        def emit(event_name: str, **payload: object) -> None:
            events.append((event_name, payload))

        with (
            patch("envctl_engine.ui.menu.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.menu.prompt_toolkit_available", return_value=True),
        ):
            build_menu_presenter({}, emit=emit)

        self.assertIn(("ui.menu.backend", {"backend": "prompt_toolkit"}), events)

    def test_terminal_session_uses_prompt_toolkit_when_enabled(self) -> None:
        with (
            patch("envctl_engine.ui.terminal_session.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.terminal_session.prompt_toolkit_available", return_value=True),
            patch("envctl_engine.ui.terminal_session._prompt_toolkit_prompt", return_value="r\r"),
            patch(
                "envctl_engine.ui.terminal_session._read_command_line_fallback",
                side_effect=AssertionError("fallback should not be used when prompt_toolkit is available"),
            ),
        ):
            session = TerminalSession({})
            value = session.read_command_line("Enter command: ")

        self.assertEqual(value, "r")

    def test_terminal_session_emits_backend_choice(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []

        def emit(event_name: str, **payload: object) -> None:
            events.append((event_name, payload))

        with (
            patch("envctl_engine.ui.terminal_session.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.terminal_session.prompt_toolkit_available", return_value=True),
            patch("envctl_engine.ui.terminal_session._prompt_toolkit_prompt", return_value="r\r"),
            patch(
                "envctl_engine.ui.terminal_session._read_command_line_fallback",
                side_effect=AssertionError("fallback should not be used when prompt_toolkit is available"),
            ),
        ):
            session = TerminalSession({}, emit=emit)
            value = session.read_command_line("Enter command: ")

        self.assertEqual(value, "r")
        self.assertIn(("ui.input.backend", {"backend": "prompt_toolkit"}), events)

    def test_terminal_session_uses_basic_input_when_prompt_toolkit_disabled(self) -> None:
        with (
            patch("envctl_engine.ui.terminal_session.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.terminal_session.prompt_toolkit_available", return_value=True),
            patch(
                "envctl_engine.ui.terminal_session._prompt_toolkit_prompt",
                side_effect=AssertionError("prompt_toolkit should be disabled by ENVCTL_UI_PROMPT_TOOLKIT"),
            ),
            patch("envctl_engine.ui.terminal_session._restore_stdin_terminal_sane"),
            patch(
                "envctl_engine.ui.terminal_session._read_command_line_fallback",
                side_effect=AssertionError("raw fallback should not be used for basic_input path"),
            ),
            patch("builtins.input", return_value="r\r"),
        ):
            session = TerminalSession({"ENVCTL_UI_PROMPT_TOOLKIT": "false"})
            value = session.read_command_line("Enter command: ")

        self.assertEqual(value, "r")

    def test_prompt_toolkit_prompt_disables_cpr_temporarily(self) -> None:
        captured = {"during": ""}

        def fake_prompt(_prompt: str) -> str:
            captured["during"] = os.environ.get("PROMPT_TOOLKIT_NO_CPR", "")
            return "ok"

        fake_module = types.SimpleNamespace(prompt=fake_prompt)
        os.environ["PROMPT_TOOLKIT_NO_CPR"] = "0"
        try:
            with patch("envctl_engine.ui.terminal_session.importlib.import_module", return_value=fake_module):
                value = terminal_session._prompt_toolkit_prompt("Enter command: ")
        finally:
            os.environ.pop("PROMPT_TOOLKIT_NO_CPR", None)

        self.assertEqual(value, "ok")
        self.assertEqual(captured["during"], "1")

    def test_runtime_terminal_ui_interactive_read_does_not_force_basic_input(self) -> None:
        captured = {"prefer": False}

        class _SessionStub:
            def __init__(self, _env: object, *, input_provider: object = None, prefer_basic_input: bool = False):
                _ = input_provider
                captured["prefer"] = bool(prefer_basic_input)

            @staticmethod
            def read_command_line(_prompt: str) -> str:
                return "r"

        with patch("envctl_engine.ui.dashboard.terminal_ui.TerminalSession", _SessionStub):
            value = RuntimeTerminalUI.read_interactive_command_line("Enter command: ", {})

        self.assertEqual(value, "r")
        self.assertFalse(captured["prefer"])

    def test_terminal_session_prefers_basic_input_when_requested(self) -> None:
        with (
            patch("envctl_engine.ui.terminal_session.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.terminal_session.prompt_toolkit_available", return_value=True),
            patch(
                "envctl_engine.ui.terminal_session._prompt_toolkit_prompt",
                side_effect=AssertionError("prompt_toolkit should be bypassed when prefer_basic_input is set"),
            ),
            patch("envctl_engine.ui.terminal_session._restore_stdin_terminal_sane"),
            patch(
                "envctl_engine.ui.terminal_session._read_command_line_fallback",
                side_effect=AssertionError("raw fallback should not be used for basic_input path"),
            ),
            patch("builtins.input", return_value="q\r"),
        ):
            session = TerminalSession({}, prefer_basic_input=True)
            value = session.read_command_line("Enter command: ")

        self.assertEqual(value, "q")

    def test_terminal_session_prefers_basic_input_when_env_flag_enabled(self) -> None:
        with (
            patch("envctl_engine.ui.terminal_session.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.terminal_session.prompt_toolkit_available", return_value=True),
            patch(
                "envctl_engine.ui.terminal_session._prompt_toolkit_prompt",
                side_effect=AssertionError("prompt_toolkit should be bypassed when ENVCTL_UI_BASIC_INPUT is set"),
            ),
            patch("envctl_engine.ui.terminal_session._restore_stdin_terminal_sane"),
            patch(
                "envctl_engine.ui.terminal_session._read_command_line_fallback",
                side_effect=AssertionError("raw fallback should not be used for basic_input path"),
            ),
            patch("builtins.input", return_value="h\r"),
        ):
            session = TerminalSession({"ENVCTL_UI_BASIC_INPUT": "true"})
            value = session.read_command_line("Enter command: ")

        self.assertEqual(value, "h")

    def test_ensure_tty_line_mode_enables_canonical_echo_signal_and_cr_translation_flags(self) -> None:
        initial = [0, 0, 0, 0, 0, 0]
        updated_states: list[list[int]] = []

        def fake_setattr(_fd: int, _when: int, attrs: object) -> None:
            if isinstance(attrs, list):
                updated_states.append(list(attrs))

        with (
            patch("termios.tcgetattr", return_value=initial),
            patch("termios.tcsetattr", side_effect=fake_setattr),
            patch("envctl_engine.ui.terminal_session.restore_terminal_after_input") as restore_mock,
        ):
            terminal_session._ensure_tty_line_mode(fd=9)

        self.assertEqual(restore_mock.call_count, 0)
        self.assertEqual(len(updated_states), 1)
        iflag = int(updated_states[0][0])
        lflag = int(updated_states[0][3])
        self.assertTrue(iflag & termios.ICRNL)
        self.assertFalse(bool(iflag & int(getattr(termios, "INLCR", 0))))
        self.assertFalse(bool(iflag & int(getattr(termios, "IGNCR", 0))))
        self.assertTrue(lflag & termios.ICANON)
        self.assertTrue(lflag & termios.ECHO)
        self.assertTrue(lflag & termios.ISIG)


if __name__ == "__main__":
    unittest.main()
