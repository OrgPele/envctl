from __future__ import annotations

import os
import pty
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import io
import select
import subprocess
import sys
import termios
import textwrap
import time

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.ui.debug_flight_recorder import DebugFlightRecorder, DebugRecorderConfig
from envctl_engine.ui import terminal_session as terminal_session_module
from envctl_engine.ui.terminal_session import TerminalSession, _restore_stdin_terminal_sane


class TerminalSessionDebugTests(unittest.TestCase):
    def _run_in_pty(self, script: str, writes: list[tuple[float, bytes]], *, timeout: float = 4.0) -> str:
        master_fd, slave_fd = pty.openpty()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PYTHON_ROOT)
        proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-c", script],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            close_fds=True,
            text=False,
        )
        os.close(slave_fd)
        output = bytearray()
        try:
            deadline = time.monotonic() + timeout
            write_index = 0
            write_start = time.monotonic()
            while time.monotonic() < deadline:
                while write_index < len(writes) and (time.monotonic() - write_start) >= writes[write_index][0]:
                    os.write(master_fd, writes[write_index][1])
                    write_index += 1
                ready, _, _ = select.select([master_fd], [], [], 0.05)
                if ready:
                    try:
                        chunk = os.read(master_fd, 8192)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output.extend(chunk)
                if proc.poll() is not None and write_index >= len(writes) and not ready:
                    break
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=3)
            return output.decode("utf-8", errors="ignore")
        finally:
            try:
                os.close(master_fd)
            except OSError:
                pass

    def test_line_reader_consumes_crlf_pair_without_empty_followup(self) -> None:
        terminal_session_module._PUSHBACK_BYTES.clear()
        reads = [b"q", b"\r", b"\n", b"h", b"\r", b"\n"]

        def fake_read(_fd: int, _count: int) -> bytes:
            if not reads:
                return b""
            return reads.pop(0)

        def fake_select(_r, _w, _x, _timeout):  # noqa: ANN001
            if reads:
                return ([9], [], [])
            return ([], [], [])

        with (
            patch("envctl_engine.ui.terminal_session.os.read", side_effect=fake_read),
            patch("envctl_engine.ui.terminal_session.select.select", side_effect=fake_select),
        ):
            first = terminal_session_module._read_line_from_fd(9)
            second = terminal_session_module._read_line_from_fd(9)

        self.assertEqual(first, "q")
        self.assertEqual(second, "h")
        terminal_session_module._PUSHBACK_BYTES.clear()

    def test_line_reader_pushes_back_non_newline_probe_byte(self) -> None:
        terminal_session_module._PUSHBACK_BYTES.clear()
        reads = [b"q", b"\r", b"x", b"h", b"\r"]

        def fake_read(_fd: int, _count: int) -> bytes:
            if not reads:
                return b""
            return reads.pop(0)

        def fake_select(_r, _w, _x, _timeout):  # noqa: ANN001
            if reads:
                return ([9], [], [])
            return ([], [], [])

        with (
            patch("envctl_engine.ui.terminal_session.os.read", side_effect=fake_read),
            patch("envctl_engine.ui.terminal_session.select.select", side_effect=fake_select),
        ):
            first = terminal_session_module._read_line_from_fd(9)
            second = terminal_session_module._read_line_from_fd(9)

        self.assertEqual(first, "q")
        self.assertEqual(second, "xh")
        terminal_session_module._PUSHBACK_BYTES.clear()

    def test_discard_stale_control_sequences_preserves_printable_input(self) -> None:
        terminal_session_module._PUSHBACK_BYTES.clear()
        reads = [b"\x1b", b"[", b"B", b"t"]

        def fake_read(_fd: int, _count: int) -> bytes:
            if not reads:
                return b""
            return reads.pop(0)

        def fake_select(_r, _w, _x, _timeout):  # noqa: ANN001
            if reads:
                return ([9], [], [])
            return ([], [], [])

        with (
            patch("envctl_engine.ui.terminal_session.os.read", side_effect=fake_read),
            patch("envctl_engine.ui.terminal_session.select.select", side_effect=fake_select),
        ):
            discarded = terminal_session_module._discard_stale_control_sequences(fd=9)
            first = terminal_session_module._read_byte(fd=9)

        self.assertEqual(discarded, 3)
        self.assertEqual(first, b"t")
        terminal_session_module._PUSHBACK_BYTES.clear()

    def test_discard_stale_control_sequences_drops_cr_without_dropping_text(self) -> None:
        terminal_session_module._PUSHBACK_BYTES.clear()
        reads = [b"\r", b"t"]

        def fake_read(_fd: int, _count: int) -> bytes:
            if not reads:
                return b""
            return reads.pop(0)

        def fake_select(_r, _w, _x, _timeout):  # noqa: ANN001
            if reads:
                return ([9], [], [])
            return ([], [], [])

        with (
            patch("envctl_engine.ui.terminal_session.os.read", side_effect=fake_read),
            patch("envctl_engine.ui.terminal_session.select.select", side_effect=fake_select),
        ):
            discarded = terminal_session_module._discard_stale_control_sequences(fd=9)
            first = terminal_session_module._read_byte(fd=9)

        self.assertEqual(discarded, 1)
        self.assertEqual(first, b"t")
        terminal_session_module._PUSHBACK_BYTES.clear()

    def test_fallback_reader_prefers_graceful_reader_and_reports_dropped_sequences(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []

        def emit(event: str, **payload: object) -> None:
            events.append((event, dict(payload)))

        class _Handle:
            def fileno(self) -> int:
                return 9

            def close(self) -> None:
                return None

        with (
            patch("envctl_engine.ui.terminal_session.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.terminal_session.open", return_value=_Handle()),
            patch("envctl_engine.ui.terminal_session.termios.tcflush"),
            patch("envctl_engine.ui.terminal_session._ensure_tty_line_mode"),
            patch("envctl_engine.ui.terminal_session._read_line_from_fd_graceful", return_value=("q", 2)),
            patch(
                "envctl_engine.ui.terminal_session._read_line_from_fd",
                side_effect=AssertionError("line reader should not be used when graceful reader succeeds"),
            ),
            patch("envctl_engine.ui.terminal_session.sys.stdout", io.StringIO()),
        ):
            value = terminal_session_module._read_command_line_fallback(
                "Enter command: ",
                {},
                lambda _prompt: "ignored",
                emit=emit,
                debug_recorder=None,
            )

        self.assertEqual(value, "q")
        end_events = [payload for name, payload in events if name == "ui.input.read.end"]
        self.assertTrue(end_events)
        self.assertEqual(end_events[-1].get("source"), "tty_graceful")
        self.assertEqual(end_events[-1].get("dropped_escape_sequences"), 2)

    def test_fallback_reader_uses_line_reader_when_graceful_reader_fails(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []

        def emit(event: str, **payload: object) -> None:
            events.append((event, dict(payload)))

        class _Handle:
            def fileno(self) -> int:
                return 9

            def close(self) -> None:
                return None

        with (
            patch("envctl_engine.ui.terminal_session.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.terminal_session.open", return_value=_Handle()),
            patch("envctl_engine.ui.terminal_session.termios.tcflush"),
            patch("envctl_engine.ui.terminal_session._ensure_tty_line_mode"),
            patch("envctl_engine.ui.terminal_session._read_line_from_fd_graceful", side_effect=RuntimeError("boom")),
            patch("envctl_engine.ui.terminal_session._read_line_from_fd", return_value="q"),
            patch("envctl_engine.ui.terminal_session.sys.stdout", io.StringIO()),
        ):
            value = terminal_session_module._read_command_line_fallback(
                "Enter command: ",
                {},
                lambda _prompt: "ignored",
                emit=emit,
                debug_recorder=None,
            )

        self.assertEqual(value, "q")
        end_events = [payload for name, payload in events if name == "ui.input.read.end"]
        self.assertTrue(end_events)
        self.assertEqual(end_events[-1].get("source"), "tty_line")
        self.assertEqual(end_events[-1].get("dropped_escape_sequences"), 0)

    def test_normalize_standard_tty_state_restores_line_mode_on_output_ttys(self) -> None:
        pendin = int(getattr(termios, "PENDIN", 0))
        if not pendin:
            self.skipTest("PENDIN not available on this platform")

        states = {
            1: [0, 0, 0, 67 | pendin, 0, 0, [b"\x00"] * 32],
            2: [0, 0, 0, 67 | pendin, 0, 0, [b"\x00"] * 32],
        }
        set_calls: list[tuple[int, int]] = []

        def fake_tcgetattr(fd: int):
            return list(states[fd])

        def fake_tcsetattr(fd: int, _when: int, updated):  # noqa: ANN001
            set_calls.append((fd, int(updated[3])))
            states[fd] = list(updated)

        class _Stream:
            def __init__(self, fd: int) -> None:
                self._fd = fd

            def fileno(self) -> int:
                return self._fd

        with (
            patch("envctl_engine.ui.terminal_session.sys.stdout", _Stream(1)),
            patch("envctl_engine.ui.terminal_session.sys.stderr", _Stream(2)),
            patch("envctl_engine.ui.terminal_session.sys.__stdout__", _Stream(1)),
            patch("envctl_engine.ui.terminal_session.sys.__stderr__", _Stream(2)),
            patch("envctl_engine.ui.terminal_session.os.isatty", return_value=True),
            patch("envctl_engine.ui.terminal_session.termios.tcgetattr", side_effect=fake_tcgetattr),
            patch("envctl_engine.ui.terminal_session.termios.tcsetattr", side_effect=fake_tcsetattr),
        ):
            terminal_session_module.normalize_standard_tty_state()

        self.assertEqual(len(set_calls), 2)
        for _fd, lflag in set_calls:
            self.assertEqual(lflag & pendin, 0)
            self.assertTrue(bool(lflag & int(termios.ICANON)))
            self.assertTrue(bool(lflag & int(termios.ECHO)))
            self.assertTrue(bool(lflag & int(termios.ISIG)))

    def test_read_command_line_emits_context_when_not_tty(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []

        def emit(event: str, **payload: object) -> None:
            events.append((event, dict(payload)))

        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = DebugFlightRecorder(
                DebugRecorderConfig(
                    runtime_scope_dir=Path(tmpdir) / "scope",
                    runtime_scope_id="repo-123",
                    run_id="run-1",
                    mode="deep",
                    bundle_strict=True,
                    capture_printable=True,
                    ring_bytes=256,
                    max_events=10,
                    sample_rate=1,
                )
            )
            session = TerminalSession(
                env={},
                input_provider=lambda _prompt: "q",
                emit=emit,
                debug_recorder=recorder,
            )
            _ = session.read_command_line("Enter command: ")

            self.assertTrue(any(name == "ui.input.read.begin" for name, _ in events))
            self.assertTrue((recorder.session_dir / "tty_context.json").is_file())

    def test_prefer_basic_input_uses_python_input_provider_when_not_deep(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []

        def emit(event: str, **payload: object) -> None:
            events.append((event, dict(payload)))

        with (
            patch("envctl_engine.ui.terminal_session.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.terminal_session._restore_stdin_terminal_sane"),
            patch("envctl_engine.ui.terminal_session._read_command_line_fallback", side_effect=AssertionError("fallback should not be used")),
        ):
            session = TerminalSession(
                env={},
                input_provider=lambda _prompt: "q",
                prefer_basic_input=True,
                emit=emit,
                debug_recorder=None,
            )
            value = session.read_command_line("Enter command: ")

        self.assertEqual(value, "q")
        backends = [payload.get("backend") for name, payload in events if name == "ui.input.backend"]
        self.assertIn("basic_input", backends)

    def test_prefer_basic_input_uses_python_input_provider_in_deep_mode(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []

        def emit(event: str, **payload: object) -> None:
            events.append((event, dict(payload)))

        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = DebugFlightRecorder(
                DebugRecorderConfig(
                    runtime_scope_dir=Path(tmpdir) / "scope",
                    runtime_scope_id="repo-123",
                    run_id="run-1",
                    mode="deep",
                    bundle_strict=True,
                    capture_printable=True,
                    ring_bytes=256,
                    max_events=10,
                    sample_rate=1,
                )
            )
            with (
                patch("envctl_engine.ui.terminal_session.can_interactive_tty", return_value=True),
                patch("envctl_engine.ui.terminal_session._restore_stdin_terminal_sane"),
                patch("envctl_engine.ui.terminal_session._read_command_line_fallback", side_effect=AssertionError("fallback should not be used")),
            ):
                session = TerminalSession(
                    env={},
                    input_provider=lambda _prompt: "r",
                    prefer_basic_input=True,
                    emit=emit,
                    debug_recorder=recorder,
                )
                value = session.read_command_line("Enter command: ")

            self.assertEqual(value, "r")
            backends = [payload.get("backend") for name, payload in events if name == "ui.input.backend"]
            self.assertIn("basic_input", backends)
            self.assertTrue((recorder.session_dir / "input_ring.hex").is_file())

    def test_default_basic_input_reads_from_fd_without_python_input_buffer(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []

        def emit(event: str, **payload: object) -> None:
            events.append((event, dict(payload)))

        fake_stdin = type("_FakeStdin", (), {"isatty": lambda self: True, "fileno": lambda self: 9})()
        fake_stdout = io.StringIO()

        with (
            patch.dict("os.environ", {"ENVCTL_UI_BASIC_INPUT_FD": "1"}, clear=False),
            patch("envctl_engine.ui.terminal_session.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.terminal_session._restore_stdin_terminal_sane"),
            patch("envctl_engine.ui.terminal_session.sys.stdin", fake_stdin),
            patch("envctl_engine.ui.terminal_session.sys.stdout", fake_stdout),
            patch("envctl_engine.ui.terminal_session.os.isatty", return_value=True),
            patch("envctl_engine.ui.terminal_session.termios.tcgetattr", return_value=[0, 0, 0, 0, 0, 0]),
            patch("envctl_engine.ui.terminal_session.termios.tcsetattr"),
            patch("envctl_engine.ui.terminal_session.termios.tcflush"),
            patch("envctl_engine.ui.terminal_session._read_line_from_fd_graceful", return_value=("t", 0)),
            patch("builtins.input", side_effect=AssertionError("builtins.input should not be called")),
        ):
            session = TerminalSession(env={}, prefer_basic_input=True, emit=emit, debug_recorder=None)
            value = session.read_command_line("Enter command: ")

        self.assertEqual(value, "t")
        end_events = [payload for name, payload in events if name == "ui.input.read.end"]
        self.assertTrue(any(payload.get("source") == "fd" for payload in end_events))

    def test_custom_basic_input_provider_skips_fd_reader(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []

        def emit(event: str, **payload: object) -> None:
            events.append((event, dict(payload)))

        with (
            patch.dict("os.environ", {"ENVCTL_UI_BASIC_INPUT_FD": "1"}, clear=False),
            patch("envctl_engine.ui.terminal_session.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.terminal_session._restore_stdin_terminal_sane"),
            patch(
                "envctl_engine.ui.terminal_session._read_line_from_fd_graceful",
                side_effect=AssertionError("fd reader should not run with custom input provider"),
            ),
        ):
            session = TerminalSession(
                env={},
                input_provider=lambda _prompt: "r",
                prefer_basic_input=True,
                emit=emit,
                debug_recorder=None,
            )
            value = session.read_command_line("Enter command: ")

        self.assertEqual(value, "r")
        end_events = [payload for name, payload in events if name == "ui.input.read.end"]
        self.assertTrue(any(payload.get("source") == "provider" for payload in end_events))

    def test_default_basic_input_with_fd_disabled_uses_tty_fallback(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []

        def emit(event: str, **payload: object) -> None:
            events.append((event, dict(payload)))

        with (
            patch.dict(
                "os.environ",
                {"ENVCTL_UI_BASIC_INPUT_FD": "0", "ENVCTL_UI_PROMPT_TOOLKIT": "0"},
                clear=False,
            ),
            patch("envctl_engine.ui.terminal_session.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.terminal_session._restore_stdin_terminal_sane"),
            patch("envctl_engine.ui.terminal_session._read_command_line_fallback", return_value="q"),
            patch("builtins.input", side_effect=AssertionError("builtins.input should not be called")),
        ):
            session = TerminalSession(env={}, prefer_basic_input=True, emit=emit, debug_recorder=None)
            value = session.read_command_line("Enter command: ")

        self.assertEqual(value, "q")
        end_events = [payload for name, payload in events if name == "ui.input.read.end"]
        self.assertTrue(any(payload.get("source") == "tty_fallback" for payload in end_events))

    def test_graceful_fd_reader_ignores_arrow_escape_without_echoing_noise(self) -> None:
        fake_stdout = io.StringIO()
        reads = [b"\x1b", b"[", b"A", b"t", b"\n"]
        attrs = [0, 0, 0, int(termios.ICANON | termios.ECHO | termios.ISIG), 0, 0, [0] * 32]

        def fake_read(_fd: int, _count: int) -> bytes:
            if not reads:
                return b""
            return reads.pop(0)

        def fake_select(_r, _w, _x, _timeout):  # noqa: ANN001
            if reads:
                return ([9], [], [])
            return ([], [], [])

        with (
            patch("envctl_engine.ui.terminal_session.termios.tcgetattr", return_value=attrs),
            patch("envctl_engine.ui.terminal_session.termios.tcsetattr"),
            patch("envctl_engine.ui.terminal_session.restore_terminal_after_input"),
            patch("envctl_engine.ui.terminal_session.os.read", side_effect=fake_read),
            patch("envctl_engine.ui.terminal_session.select.select", side_effect=fake_select),
            patch("envctl_engine.ui.terminal_session.sys.stdout", fake_stdout),
            patch("envctl_engine.ui.terminal_session.sys.__stdout__", fake_stdout),
        ):
            text, dropped = terminal_session_module._read_line_from_fd_graceful(9)

        self.assertEqual(text, "t")
        self.assertEqual(dropped, 1)
        output = fake_stdout.getvalue()
        self.assertIn("t", output)
        self.assertNotIn("[A", output)

    def test_graceful_fd_reader_decodes_csi_u_printable_key_sequence(self) -> None:
        fake_stdout = io.StringIO()
        reads = [b"\x1b", b"[", b"1", b"1", b"3", b"u", b"\n"]
        attrs = [0, 0, 0, int(termios.ICANON | termios.ECHO | termios.ISIG), 0, 0, [0] * 32]

        def fake_read(_fd: int, _count: int) -> bytes:
            if not reads:
                return b""
            return reads.pop(0)

        def fake_select(_r, _w, _x, _timeout):  # noqa: ANN001
            if reads:
                return ([9], [], [])
            return ([], [], [])

        with (
            patch("envctl_engine.ui.terminal_session.termios.tcgetattr", return_value=attrs),
            patch("envctl_engine.ui.terminal_session.termios.tcsetattr"),
            patch("envctl_engine.ui.terminal_session.restore_terminal_after_input"),
            patch("envctl_engine.ui.terminal_session.os.read", side_effect=fake_read),
            patch("envctl_engine.ui.terminal_session.select.select", side_effect=fake_select),
            patch("envctl_engine.ui.terminal_session.sys.stdout", fake_stdout),
            patch("envctl_engine.ui.terminal_session.sys.__stdout__", fake_stdout),
        ):
            text, dropped = terminal_session_module._read_line_from_fd_graceful(9)

        self.assertEqual(text, "q")
        self.assertEqual(dropped, 0)
        output = fake_stdout.getvalue()
        self.assertIn("q", output)

    def test_restore_stdin_terminal_sane_resets_escape_modes_for_apple_terminal(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []

        def emit(event: str, **payload: object) -> None:
            events.append((event, dict(payload)))

        fake_stdin = type("_FakeStdin", (), {"fileno": lambda self: 0})()
        fake_stdout = io.StringIO()
        with (
            patch("envctl_engine.ui.terminal_session.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.terminal_session._ensure_tty_line_mode"),
            patch("envctl_engine.ui.terminal_session.sys.stdin", fake_stdin),
            patch("envctl_engine.ui.terminal_session.sys.stdout", fake_stdout),
            patch("envctl_engine.ui.terminal_session.sys.__stdout__", fake_stdout),
            patch.dict("os.environ", {"TERM_PROGRAM": "Apple_Terminal"}, clear=False),
        ):
            _restore_stdin_terminal_sane(emit=emit)

        output = fake_stdout.getvalue()
        self.assertIn("\x1b[?1000l", output)
        self.assertIn("\x1b[?1006l", output)
        reset_events = [payload for name, payload in events if name == "ui.tty.transition"]
        self.assertTrue(any(payload.get("action") == "reset_escape_modes" for payload in reset_events))

    def test_restore_stdin_terminal_sane_skips_escape_mode_reset_when_not_apple_terminal(self) -> None:
        fake_stdin = type("_FakeStdin", (), {"fileno": lambda self: 0})()
        fake_stdout = io.StringIO()
        with (
            patch("envctl_engine.ui.terminal_session.can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.terminal_session._ensure_tty_line_mode"),
            patch("envctl_engine.ui.terminal_session.sys.stdin", fake_stdin),
            patch("envctl_engine.ui.terminal_session.sys.stdout", fake_stdout),
            patch("envctl_engine.ui.terminal_session.sys.__stdout__", fake_stdout),
            patch.dict("os.environ", {"TERM_PROGRAM": "vscode", "ENVCTL_UI_RESET_ESCAPE_MODES": "auto"}, clear=False),
        ):
            _restore_stdin_terminal_sane()

        self.assertNotIn("\x1b[?1000l", fake_stdout.getvalue())

    def test_basic_input_restore_completes_cleanly_before_followup_consumer_in_pty(self) -> None:
        script = textwrap.dedent(
            f"""
            import os
            import select
            import sys
            import termios
            import tty

            sys.path.insert(0, {str(PYTHON_ROOT)!r})

            from envctl_engine.ui.terminal_session import TerminalSession

            session = TerminalSession({{}}, prefer_basic_input=True)
            command = session.read_command_line("Enter command: ")
            print("CMD=" + repr(command), flush=True)
            old = termios.tcgetattr(0)
            try:
                tty.setraw(0)
                for idx in range(5):
                    ready, _, _ = select.select([0], [], [], 0.1)
                    if not ready:
                        print(f"PENDING_{{idx}}=none", flush=True)
                        continue
                    data = os.read(0, 64)
                    print(f"PENDING_{{idx}}={{data!r}}", flush=True)
            finally:
                termios.tcsetattr(0, termios.TCSADRAIN, old)
            """
        )

        output = self._run_in_pty(
            script,
            [
                (0.2, b"t\r"),
                (0.21, b"\x1b[B" * 3),
            ],
        )

        self.assertIn("CMD='t'", output)


if __name__ == "__main__":
    unittest.main()
