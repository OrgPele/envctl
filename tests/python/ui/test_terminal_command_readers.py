from __future__ import annotations

from types import SimpleNamespace
import unittest

from envctl_engine.ui.terminal_command_readers import TerminalCommandReaderDeps, read_command_line_basic


class TerminalCommandReaderTests(unittest.TestCase):
    def test_basic_reader_uses_provider_when_fd_reader_is_disabled(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []

        text = read_command_line_basic(
            "cmd> ",
            lambda _prompt: "status\n",
            deps=TerminalCommandReaderDeps(
                environ={"ENVCTL_UI_BASIC_INPUT_FD": "0"},
                stdin=SimpleNamespace(isatty=lambda: True),
                stdout=SimpleNamespace(isatty=lambda: True, write=lambda _text: None, flush=lambda: None),
                stdout_fallback=SimpleNamespace(write=lambda _text: None, flush=lambda: None),
                can_interactive_tty=lambda: True,
                os_isatty=lambda _fd: True,
                stdin_fileno=lambda: 9,
                open_tty=lambda _path: None,
                ensure_tty_line_mode=lambda *, fd: None,
                discard_stale_control_sequences=lambda *, fd: 0,
                read_line_from_fd_graceful=lambda fd, on_bytes=None, emit=None: ("ignored", 0),
                read_line_from_fd=lambda fd, on_bytes=None: "ignored",
                read_command_line_fallback=None,
                basic_input_fd_enabled=lambda: False,
                restore_terminal_after_input=lambda *, fd, original_state, emit=None: None,
                canonical_line_state=lambda *, fd: None,
            ),
            input_provider_is_default=True,
            emit=lambda event, **payload: events.append((event, payload)),
        )

        self.assertEqual(text, "status\n")
        self.assertIn(
            ("ui.input.read.end", {"component": "ui.terminal_session", "backend": "basic_input", "bytes_read": 7, "source": "provider"}),
            events,
        )

    def test_basic_reader_prefers_fd_reader_when_enabled(self) -> None:
        byte_chunks: list[bytes] = []

        def read_line(_fd, *, on_bytes=None, emit=None):  # noqa: ANN001, ANN202
            if on_bytes is not None:
                on_bytes(b"q\n")
            return "q\n", 0

        text = read_command_line_basic(
            "cmd> ",
            lambda _prompt: "ignored",
            deps=TerminalCommandReaderDeps(
                environ={},
                stdin=SimpleNamespace(isatty=lambda: True),
                stdout=SimpleNamespace(isatty=lambda: True, write=lambda _text: None, flush=lambda: None),
                stdout_fallback=SimpleNamespace(write=lambda _text: None, flush=lambda: None),
                can_interactive_tty=lambda: True,
                os_isatty=lambda _fd: True,
                stdin_fileno=lambda: 9,
                open_tty=lambda _path: None,
                ensure_tty_line_mode=lambda *, fd: None,
                discard_stale_control_sequences=lambda *, fd: 0,
                read_line_from_fd_graceful=read_line,
                read_line_from_fd=lambda fd, on_bytes=None: "ignored",
                read_command_line_fallback=None,
                basic_input_fd_enabled=lambda: True,
                restore_terminal_after_input=lambda *, fd, original_state, emit=None: None,
                canonical_line_state=lambda *, fd: None,
                record_input_bytes=lambda data, *, component, backend: byte_chunks.append(data),
            ),
            input_provider_is_default=True,
            debug_recorder=SimpleNamespace(
                config=SimpleNamespace(mode="deep"),
                write_tty_context=lambda _payload: None,
                append_tty_state_transition=lambda _payload: None,
            ),
        )

        self.assertEqual(text, "q\n")
        self.assertEqual(byte_chunks, [b"q\n"])


if __name__ == "__main__":
    unittest.main()
