from __future__ import annotations

import io
import termios
import unittest

from envctl_engine.ui.terminal_input_stream import TerminalInputBuffer, decode_escape_printable


class TerminalInputStreamTests(unittest.TestCase):
    def test_read_line_consumes_crlf_pair_without_empty_followup(self) -> None:
        buffer = TerminalInputBuffer()
        reads = [b"q", b"\r", b"\n", b"h", b"\r", b"\n"]

        def read_fn(_fd: int, _count: int) -> bytes:
            if not reads:
                return b""
            return reads.pop(0)

        def select_fn(_r, _w, _x, _timeout):  # noqa: ANN001
            if reads:
                return ([9], [], [])
            return ([], [], [])

        first = buffer.read_line_from_fd(9, read_fn=read_fn, select_fn=select_fn)
        second = buffer.read_line_from_fd(9, read_fn=read_fn, select_fn=select_fn)

        self.assertEqual(first, "q")
        self.assertEqual(second, "h")

    def test_discard_stale_control_sequences_preserves_printable_followup(self) -> None:
        buffer = TerminalInputBuffer()
        reads = [b"\x1b", b"[", b"B", b"t"]

        def read_fn(_fd: int, _count: int) -> bytes:
            if not reads:
                return b""
            return reads.pop(0)

        def select_fn(_r, _w, _x, _timeout):  # noqa: ANN001
            if reads:
                return ([9], [], [])
            return ([], [], [])

        discarded = buffer.discard_stale_control_sequences(fd=9, read_fn=read_fn, select_fn=select_fn)
        first = buffer.read_byte(fd=9, read_fn=read_fn)

        self.assertEqual(discarded, 3)
        self.assertEqual(first, b"t")

    def test_graceful_reader_drops_arrow_escape_and_decodes_printable_text(self) -> None:
        buffer = TerminalInputBuffer()
        fake_stdout = io.StringIO()
        reads = [b"\x1b", b"[", b"A", b"t", b"\n"]
        attrs = [0, 0, 0, int(termios.ICANON | termios.ECHO | termios.ISIG), 0, 0, [0] * 32]

        def read_fn(_fd: int, _count: int) -> bytes:
            if not reads:
                return b""
            return reads.pop(0)

        def select_fn(_r, _w, _x, _timeout):  # noqa: ANN001
            if reads:
                return ([9], [], [])
            return ([], [], [])

        text, dropped = buffer.read_line_from_fd_graceful(
            9,
            read_fn=read_fn,
            select_fn=select_fn,
            stdout=fake_stdout,
            tcgetattr=lambda _fd: attrs,
            set_character_mode=lambda **_kwargs: True,
            restore_input=lambda **_kwargs: None,
        )

        self.assertEqual(text, "t")
        self.assertEqual(dropped, 1)
        self.assertIn("t", fake_stdout.getvalue())
        self.assertNotIn("[A", fake_stdout.getvalue())

    def test_decode_escape_printable_supports_csi_u_sequences(self) -> None:
        self.assertEqual(decode_escape_printable(b"[113u"), "q")
        self.assertIsNone(decode_escape_printable(b"[not-a-codepointu"))


if __name__ == "__main__":
    unittest.main()
