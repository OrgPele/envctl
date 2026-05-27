from __future__ import annotations

from envctl_engine.ui.textual.screens.selector.io_probe import SelectorIoProbe


class _Stream:
    def __init__(self, value: object) -> None:
        self.value = value

    def fileno(self) -> object:
        return self.value


class _BrokenStream:
    def fileno(self) -> int:
        raise OSError("no fd")


def test_fd_value_accepts_ints_and_fileno_objects() -> None:
    probe = SelectorIoProbe()

    assert probe.fd_value(9) == 9
    assert probe.fd_value(_Stream(10)) == 10
    assert probe.fd_value(_Stream("10")) is None
    assert probe.fd_value(_BrokenStream()) is None
    assert probe.fd_value(object()) is None


def test_safe_fileno_rejects_negative_and_non_integer_values() -> None:
    probe = SelectorIoProbe()

    assert probe.safe_fileno(_Stream(3)) == 3
    assert probe.safe_fileno(_Stream(-1)) is None
    assert probe.safe_fileno(_Stream("3")) is None
    assert probe.safe_fileno(_BrokenStream()) is None


def test_unavailable_termios_and_pending_byte_snapshots_are_stable() -> None:
    probe = SelectorIoProbe()

    assert probe.termios_snapshot(None) == {}
    assert probe.termios_snapshot(-1) == {}
    assert probe.pending_bytes_snapshot(None) is None
    assert probe.pending_bytes_snapshot(-1) is None
    assert probe.tty_name(None) == ""
    assert probe.tty_name(-1) == ""
