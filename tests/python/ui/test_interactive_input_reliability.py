from __future__ import annotations

import unittest
import termios
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime


class InteractiveInputReliabilityTests(unittest.TestCase):
    def _runtime(self) -> PythonEngineRuntime:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
            }
        )
        return PythonEngineRuntime(config, env={})

    def test_sanitize_interactive_input_removes_csi_sequences(self) -> None:
        raw = "status \x1b[A"
        cleaned = PythonEngineRuntime._sanitize_interactive_input(raw)
        self.assertEqual(cleaned, "status")

    def test_sanitize_interactive_input_removes_ss3_sequences(self) -> None:
        raw = "status \x1bOA"
        cleaned = PythonEngineRuntime._sanitize_interactive_input(raw)
        self.assertEqual(cleaned, "status")

    def test_sanitize_interactive_input_removes_control_sequences(self) -> None:
        raw = "status \x1b[1;5A now"
        cleaned = PythonEngineRuntime._sanitize_interactive_input(raw)
        self.assertEqual(cleaned, "status now")

    def test_sanitize_interactive_input_preserves_single_letter_command_after_bracket_fragment(self) -> None:
        raw = "[s"
        cleaned = PythonEngineRuntime._sanitize_interactive_input(raw)
        self.assertEqual(cleaned, "s")

    def test_sanitize_interactive_input_recovers_single_letter_command_from_ss3_fragment(self) -> None:
        raw = "\x1bOs"
        cleaned = PythonEngineRuntime._sanitize_interactive_input(raw)
        self.assertEqual(cleaned, "s")

    def test_sanitize_interactive_input_recovers_single_letter_command_from_csi_modifier_fragment(self) -> None:
        raw = "\x1b[1;5s"
        cleaned = PythonEngineRuntime._sanitize_interactive_input(raw)
        self.assertEqual(cleaned, "s")

    def test_sanitize_interactive_input_preserves_command_with_carriage_return(self) -> None:
        raw = "r\r"
        cleaned = PythonEngineRuntime._sanitize_interactive_input(raw)
        self.assertEqual(cleaned, "r")

    def test_decode_planning_menu_escape_maps_arrow_keys(self) -> None:
        self.assertEqual(PythonEngineRuntime._decode_planning_menu_escape(b"[A"), "up")
        self.assertEqual(PythonEngineRuntime._decode_planning_menu_escape(b"[B"), "down")
        self.assertEqual(PythonEngineRuntime._decode_planning_menu_escape(b"[1;5C"), "right")
        self.assertEqual(PythonEngineRuntime._decode_planning_menu_escape(b"OD"), "left")

    def test_decode_planning_menu_escape_rejects_unknown_sequences(self) -> None:
        self.assertIsNone(PythonEngineRuntime._decode_planning_menu_escape(b"[Z"))
        self.assertIsNone(PythonEngineRuntime._decode_planning_menu_escape(b""))

    def test_flush_pending_interactive_input_drains_bytes_when_tcflush_fails(self) -> None:
        fake_stdin = SimpleNamespace(isatty=lambda: True, fileno=lambda: 9)
        select_calls: list[int] = []
        read_calls: list[int] = []

        def fake_select(read_fds, _write_fds, _error_fds, _timeout):  # noqa: ANN001
            select_calls.append(1)
            if len(select_calls) == 1:
                return (read_fds, [], [])
            return ([], [], [])

        def fake_read(_fd: int, _count: int) -> bytes:
            read_calls.append(1)
            return b"\n"

        with (
            patch("envctl_engine.runtime.engine_runtime.sys.stdin", fake_stdin),
            patch("termios.tcflush", side_effect=OSError("unsupported")),
            patch("select.select", side_effect=fake_select),
            patch("os.read", side_effect=fake_read),
        ):
            PythonEngineRuntime._flush_pending_interactive_input()

        self.assertGreaterEqual(len(select_calls), 1)
        self.assertEqual(len(read_calls), 1)

    def test_flush_pending_interactive_input_drains_more_than_legacy_32_byte_cap(self) -> None:
        fake_stdin = SimpleNamespace(isatty=lambda: True, fileno=lambda: 9)
        select_calls: list[int] = []
        read_calls: list[int] = []
        remaining = 80

        def fake_select(read_fds, _write_fds, _error_fds, _timeout):  # noqa: ANN001
            select_calls.append(1)
            if remaining > 0:
                return (read_fds, [], [])
            return ([], [], [])

        def fake_read(_fd: int, _count: int) -> bytes:
            nonlocal remaining
            if remaining <= 0:
                return b""
            remaining -= 1
            read_calls.append(1)
            return b"x"

        with (
            patch("envctl_engine.runtime.engine_runtime.sys.stdin", fake_stdin),
            patch("termios.tcflush", side_effect=OSError("unsupported")),
            patch("select.select", side_effect=fake_select),
            patch("os.read", side_effect=fake_read),
        ):
            PythonEngineRuntime._flush_pending_interactive_input()

        self.assertGreaterEqual(len(select_calls), 1)
        self.assertEqual(len(read_calls), 80)

    def test_read_planning_menu_key_ignores_orphan_bracket_escape_fragment(self) -> None:
        runtime = self._runtime()

        os_read_values = [b"[", b"B"]

        def fake_read(_fd: int, _count: int) -> bytes:
            if os_read_values:
                return os_read_values.pop(0)
            return b""

        def fake_select(_read_fds, _write_fds, _error_fds, _timeout):  # noqa: ANN001
            if os_read_values:
                return ([_read_fds[0]], [], [])
            return ([], [], [])

        with patch("os.read", side_effect=fake_read):
            key = runtime._read_planning_menu_key(fd=9, selector=fake_select)
        self.assertEqual(key, "noop")

    def test_read_planning_menu_key_decodes_escape_prefixed_arrow(self) -> None:
        runtime = self._runtime()
        os_read_values = [b"\x1b", b"[", b"B"]

        def fake_read(_fd: int, _count: int) -> bytes:
            if os_read_values:
                return os_read_values.pop(0)
            return b""

        def fake_select(_read_fds, _write_fds, _error_fds, _timeout):  # noqa: ANN001
            if os_read_values:
                return ([_read_fds[0]], [], [])
            return ([], [], [])

        with patch("os.read", side_effect=fake_read):
            key = runtime._read_planning_menu_key(fd=9, selector=fake_select)
        self.assertEqual(key, "down")

    def test_read_planning_menu_key_decodes_escape_prefixed_letter_modifier_sequence(self) -> None:
        runtime = self._runtime()
        os_read_values = [b"\x1b", b"[", b"1", b"1", b"5", b";", b"1", b"u"]

        def fake_read(_fd: int, _count: int) -> bytes:
            if os_read_values:
                return os_read_values.pop(0)
            return b""

        def fake_select(_read_fds, _write_fds, _error_fds, _timeout):  # noqa: ANN001
            if os_read_values:
                return ([_read_fds[0]], [], [])
            return ([], [], [])

        with patch("os.read", side_effect=fake_read):
            key = runtime._read_planning_menu_key(fd=9, selector=fake_select)
        self.assertEqual(key, "down")

    def test_read_planning_menu_key_decodes_escape_prefixed_alt_letter(self) -> None:
        runtime = self._runtime()
        os_read_values = [b"\x1b", b"s"]

        def fake_read(_fd: int, _count: int) -> bytes:
            if os_read_values:
                return os_read_values.pop(0)
            return b""

        def fake_select(_read_fds, _write_fds, _error_fds, _timeout):  # noqa: ANN001
            if os_read_values:
                return ([_read_fds[0]], [], [])
            return ([], [], [])

        with patch("os.read", side_effect=fake_read):
            key = runtime._read_planning_menu_key(fd=9, selector=fake_select)
        self.assertEqual(key, "down")

    def test_read_interactive_command_line_ensures_line_mode_before_read(self) -> None:
        runtime = self._runtime()
        restore_calls: list[tuple[int, list[int]]] = []
        fake_stdin = SimpleNamespace(isatty=lambda: True, fileno=lambda: 9)

        with (
            patch.object(runtime, "_can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.terminal_session.sys.stdin", fake_stdin),
            patch("envctl_engine.ui.terminal_session.can_interactive_tty", return_value=True),
            patch("termios.tcgetattr", return_value=[0, 0, 0, termios.ISIG, 0, 0]),
            patch("builtins.input", return_value="q"),
            patch(
                "termios.tcsetattr",
                side_effect=lambda _fd, when, state: restore_calls.append((when, list(state))),
            ),
        ):
            line = runtime._read_interactive_command_line("Enter command: ")

        self.assertEqual(line, "q")
        self.assertGreaterEqual(len(restore_calls), 1)
        self.assertEqual(restore_calls[0][0], termios.TCSADRAIN)
        attrs = restore_calls[0][1]
        iflag = int(attrs[0])
        self.assertTrue(iflag & termios.ICRNL)
        self.assertFalse(bool(iflag & int(getattr(termios, "INLCR", 0))))
        self.assertFalse(bool(iflag & int(getattr(termios, "IGNCR", 0))))

    def test_engine_runtime_read_interactive_command_line_defaults_to_basic_input_backend(self) -> None:
        runtime = self._runtime()
        seen: dict[str, object] = {}

        class _SessionStub:
            def __init__(
                self,
                _env: object,
                *,
                input_provider: object = None,
                prefer_basic_input: bool = False,
                emit: object = None,
                debug_recorder: object = None,
            ):
                _ = input_provider
                _ = emit
                _ = debug_recorder
                seen["prefer_basic_input"] = bool(prefer_basic_input)

            @staticmethod
            def read_command_line(_prompt: str) -> str:
                return "q"

        with patch("envctl_engine.ui.terminal_session.TerminalSession", _SessionStub):
            value = runtime._read_interactive_command_line("Enter command: ")

        self.assertEqual(value, "q")
        self.assertTrue(bool(seen.get("prefer_basic_input")))

    def test_engine_runtime_read_interactive_command_line_allows_opt_out_of_basic_input_backend(self) -> None:
        runtime = self._runtime()
        runtime.env["ENVCTL_UI_BASIC_INPUT"] = "false"
        seen: dict[str, object] = {}

        class _SessionStub:
            def __init__(
                self,
                _env: object,
                *,
                input_provider: object = None,
                prefer_basic_input: bool = False,
                emit: object = None,
                debug_recorder: object = None,
            ):
                _ = input_provider
                _ = emit
                _ = debug_recorder
                seen["prefer_basic_input"] = bool(prefer_basic_input)

            @staticmethod
            def read_command_line(_prompt: str) -> str:
                return "q"

        with patch("envctl_engine.ui.terminal_session.TerminalSession", _SessionStub):
            value = runtime._read_interactive_command_line("Enter command: ")

        self.assertEqual(value, "q")
        self.assertFalse(bool(seen.get("prefer_basic_input")))


if __name__ == "__main__":
    unittest.main()
