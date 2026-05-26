from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SelectorIoProbe:
    def fd_value(self, item: object) -> int | None:
        if isinstance(item, int):
            return item
        fileno = getattr(item, "fileno", None)
        if not callable(fileno):
            return None
        try:
            value = fileno()
        except Exception:
            return None
        return value if isinstance(value, int) else None

    def safe_fileno(self, stream: object) -> int | None:
        value = self.fd_value(stream)
        return value if isinstance(value, int) and value >= 0 else None

    def termios_snapshot(self, fd: int | None) -> dict[str, object]:
        if not isinstance(fd, int) or fd < 0:
            return {}
        state: dict[str, object] = {"fd": int(fd)}
        try:
            import termios

            attrs = termios.tcgetattr(fd)
            state.update(self._termios_lflag_state(int(attrs[3]), termios_module=termios))
        except Exception as exc:
            state["termios_error"] = type(exc).__name__
        return state

    def pending_bytes_snapshot(self, fd: int | None) -> int | None:
        if not isinstance(fd, int) or fd < 0:
            return None
        try:
            import array
            import fcntl
            import termios

            request = int(getattr(termios, "FIONREAD"))
            value = array.array("i", [0])
            fcntl.ioctl(fd, request, value, True)
            pending = int(value[0])
            return pending if pending >= 0 else 0
        except Exception:
            return None

    def tty_name(self, fd: int | None) -> str:
        if not isinstance(fd, int) or fd < 0:
            return ""
        try:
            return str(os.ttyname(fd))
        except Exception:
            return ""

    def prompt_toolkit_termios_snapshot(self, fd: int) -> dict[str, object]:
        try:
            import termios

            attrs = termios.tcgetattr(fd)
            return self._termios_lflag_state(int(attrs[3]), termios_module=termios)
        except Exception:
            return {"termios_error": True}

    def _termios_lflag_state(self, lflag: int, *, termios_module: object) -> dict[str, object]:
        return {
            "lflag": lflag,
            "canonical": bool(lflag & int(getattr(termios_module, "ICANON"))),
            "echo": bool(lflag & int(getattr(termios_module, "ECHO"))),
            "isig": bool(lflag & int(getattr(termios_module, "ISIG"))),
        }
