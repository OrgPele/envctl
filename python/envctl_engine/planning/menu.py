from __future__ import annotations

import os
import re
import select
import shutil
import subprocess
import sys
import termios
import time
import tty
from dataclasses import dataclass
from typing import Any, Callable, cast

from envctl_engine.ui.terminal_session import can_interactive_tty, prompt_toolkit_available


@dataclass(slots=True)
class PlanningMenuResult:
    selected_counts: dict[str, int]
    cancelled: bool = False


class PlanningSelectionMenu:
    def run(
        self,
        *,
        planning_files: list[str],
        selected_counts: dict[str, int],
        existing_counts: dict[str, int],
    ) -> PlanningMenuResult:
        if not planning_files:
            return PlanningMenuResult(selected_counts={})

        if self._prompt_toolkit_enabled():
            result = self._run_prompt_toolkit(
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )
            if result is not None:
                return result

        return self._run_legacy(
            planning_files=planning_files,
            selected_counts=selected_counts,
            existing_counts=existing_counts,
        )

    def _run_legacy(
        self,
        *,
        planning_files: list[str],
        selected_counts: dict[str, int],
        existing_counts: dict[str, int],
    ) -> PlanningMenuResult:
        cursor = 0
        message = ""
        fd = sys.stdin.fileno()
        original_state = termios.tcgetattr(fd)
        try:
            self.flush_pending_input(fd=fd)
            tty.setraw(fd)
            sys.stdout.write("\033[?25l")
            sys.stdout.flush()
            while True:
                frame = self.render(
                    planning_files=planning_files,
                    selected_counts=selected_counts,
                    existing_counts=existing_counts,
                    cursor=cursor,
                    message=message,
                )
                sys.stdout.write("\r\033[H\033[J")
                sys.stdout.write(self.to_terminal_lines(frame))
                sys.stdout.flush()

                key = self.read_key(fd=fd, selector=select.select)
                cursor, action, message = self.apply_key(
                    key=key,
                    cursor=cursor,
                    planning_files=planning_files,
                    selected_counts=selected_counts,
                    existing_counts=existing_counts,
                )
                if action == "submit":
                    has_existing = any(int(existing_counts.get(plan_file, 0)) > 0 for plan_file in planning_files)
                    return PlanningMenuResult(
                        selected_counts=(
                            dict(selected_counts)
                            if has_existing
                            else {plan_file: count for plan_file, count in selected_counts.items() if count > 0}
                        )
                    )
                if action == "cancel":
                    return PlanningMenuResult(selected_counts={}, cancelled=True)
        finally:
            self._flush_input_buffer(fd=fd)
            self._restore_terminal_state(fd=fd, original_state=original_state)
            self._flush_input_buffer(fd=fd)
            sys.stdout.write("\033[0m\033[?25h\n")
            sys.stdout.flush()

    def _run_prompt_toolkit(
        self,
        *,
        planning_files: list[str],
        selected_counts: dict[str, int],
        existing_counts: dict[str, int],
    ) -> PlanningMenuResult | None:
        if not planning_files:
            return PlanningMenuResult(selected_counts={})

        try:
            from prompt_toolkit.application import Application
            from prompt_toolkit.formatted_text import ANSI
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.layout import Layout
            from prompt_toolkit.layout.controls import FormattedTextControl
            from prompt_toolkit.layout.containers import Window
        except Exception:
            return None

        cursor = 0
        message = ""

        def build_frame() -> ANSI:
            frame = self.render(
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
                cursor=cursor,
                message=message,
            )
            return ANSI(frame)

        control = FormattedTextControl(text=build_frame, focusable=False)
        layout = Layout(Window(content=control))
        bindings = KeyBindings()

        def handle_key(action_key: str, event) -> None:  # noqa: ANN001
            nonlocal cursor, message
            cursor, action, message = self.apply_key(
                key=action_key,
                cursor=cursor,
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )
            if action == "submit":
                has_existing = any(int(existing_counts.get(plan_file, 0)) > 0 for plan_file in planning_files)
                event.app.exit(
                    result=PlanningMenuResult(
                        selected_counts=(
                            dict(selected_counts)
                            if has_existing
                            else {plan_file: count for plan_file, count in selected_counts.items() if count > 0}
                        )
                    )
                )
                return
            if action == "cancel":
                event.app.exit(result=PlanningMenuResult(selected_counts={}, cancelled=True))
                return
            event.app.invalidate()

        for key in ("up", "k", "w"):
            bindings.add(key)(lambda event, k="up": handle_key(k, event))
        for key in ("down", "j", "s"):
            bindings.add(key)(lambda event, k="down": handle_key(k, event))
        for key in ("left", "h"):
            bindings.add(key)(lambda event, k="left": handle_key(k, event))
        for key in ("right", "l"):
            bindings.add(key)(lambda event, k="right": handle_key(k, event))
        for key in (" ", "x"):
            bindings.add(key)(lambda event, k="space": handle_key(k, event))
        for key in ("a",):
            bindings.add(key)(lambda event, k="all": handle_key(k, event))
        for key in ("n",):
            bindings.add(key)(lambda event, k="none": handle_key(k, event))
        for key in ("+", "="):
            bindings.add(key)(lambda event, k="inc": handle_key(k, event))
        for key in ("-", "_"):
            bindings.add(key)(lambda event, k="dec": handle_key(k, event))
        bindings.add("enter")(lambda event, k="enter": handle_key(k, event))
        bindings.add("escape")(lambda event, k="quit": handle_key(k, event))
        bindings.add("c-c")(lambda event, k="quit": handle_key(k, event))
        bindings.add("q")(lambda event, k="quit": handle_key(k, event))

        app = Application(layout=layout, key_bindings=bindings, full_screen=True)
        try:
            result = app.run()
        except (EOFError, KeyboardInterrupt):
            return PlanningMenuResult(selected_counts={}, cancelled=True)
        if isinstance(result, PlanningMenuResult):
            return result
        return PlanningMenuResult(selected_counts={}, cancelled=True)

    @staticmethod
    def _prompt_toolkit_enabled() -> bool:
        if not can_interactive_tty():
            return False
        raw = os.environ.get("ENVCTL_UI_PROMPT_TOOLKIT")
        if raw is not None and str(raw).strip().lower() in {"0", "false", "no", "off"}:
            return False
        return prompt_toolkit_available()

    def render(
        self,
        *,
        planning_files: list[str],
        selected_counts: dict[str, int],
        existing_counts: dict[str, int],
        cursor: int,
        message: str,
        terminal_width: int | None = None,
        terminal_height: int | None = None,
    ) -> str:
        width, height = self.terminal_size()
        if terminal_width is not None:
            width = max(40, int(terminal_width))
        if terminal_height is not None:
            height = max(10, int(terminal_height))

        total = len(planning_files)
        cursor = max(0, min(cursor, max(total - 1, 0)))

        header_lines = 4
        footer_lines = 3 if message else 2
        visible_rows = max(5, height - header_lines - footer_lines)

        if total <= visible_rows:
            start = 0
            end = total
        else:
            half = visible_rows // 2
            start = max(0, cursor - half)
            end = start + visible_rows
            if end > total:
                end = total
                start = max(0, end - visible_rows)

        no_color = bool(os.environ.get("NO_COLOR"))
        reset = "" if no_color else "\033[0m"
        bold = "" if no_color else "\033[1m"
        dim = "" if no_color else "\033[2m"
        cyan = "" if no_color else "\033[36m"
        blue = "" if no_color else "\033[34m"
        green = "" if no_color else "\033[32m"
        yellow = "" if no_color else "\033[33m"
        magenta = "" if no_color else "\033[35m"
        red = "" if no_color else "\033[31m"

        lines: list[str] = []
        lines.append(f"{bold}{cyan}Planning Selection{reset}")
        legend = "UP/DOWN or j/k move  LEFT/RIGHT or h/l count  Space/x toggle  a all  n none  Enter run  q cancel"
        lines.append(f"{dim}{self.truncate_text(legend, width)}{reset}")
        lines.append("")
        for index in range(start, end):
            plan_file = planning_files[index]
            is_cursor = index == cursor
            pointer = f"{magenta}▶{reset}" if is_cursor else " "
            selected = int(selected_counts.get(plan_file, 0))
            existing = int(existing_counts.get(plan_file, 0))
            count_color = green if selected > 0 else yellow
            label_color = blue if is_cursor else ""
            prefix_plain = f" {'▶' if is_cursor else ' '} [{selected}x] "
            detail_plain = f" (existing {existing}x)" if existing > 0 else ""
            name_budget = width - len(prefix_plain) - len(detail_plain)
            if name_budget < 8:
                detail_plain = ""
                name_budget = width - len(prefix_plain)
            name_display = self.truncate_text(plan_file, name_budget)
            detail = f"{dim}{detail_plain}{reset}" if detail_plain else ""
            lines.append(f" {pointer} {count_color}[{selected}x]{reset} {label_color}{name_display}{reset}{detail}")

        lines.append("")
        selected_total = sum(1 for value in selected_counts.values() if int(value) > 0)
        lines.append(f"{dim}Selected plans: {selected_total}  Showing {start + 1}-{end} of {total}{reset}")
        if message:
            lines.append(f"{red}{self.truncate_text(message, width)}{reset}")
        return "\n".join(lines)

    def read_key(self, *, fd: int, selector: Callable[..., object]) -> str:
        first = os.read(fd, 1)
        if not first:
            return "noop"
        mapped = self._map_single_byte_key(first)
        if mapped is not None:
            return mapped
        if first in {b"[", b"O"}:
            return "noop"
        if first != b"\x1b":
            return "noop"

        sequence = self.read_escape_sequence(fd=fd, selector=selector, timeout=0.03, max_bytes=16)
        if not sequence:
            return "esc"
        decoded = self.decode_escape(sequence)
        if decoded is not None:
            return decoded
        printable = self.decode_modified_printable(sequence)
        if printable is not None:
            mapped_printable = self._map_single_byte_key(printable.encode("latin-1", errors="ignore"))
            if mapped_printable is not None:
                return mapped_printable
        return "noop"

    @staticmethod
    def _map_single_byte_key(first: bytes) -> str | None:
        if first in {b"\r", b"\n"}:
            return "enter"
        if first == b" ":
            return "space"
        if first in {b"q", b"Q", b"\x03"}:
            return "quit"
        if first in {b"a", b"A"}:
            return "all"
        if first in {b"n", b"N"}:
            return "none"
        if first in {b"k", b"K", b"w", b"W"}:
            return "up"
        if first in {b"j", b"J", b"s", b"S"}:
            return "down"
        if first in {b"h", b"H"}:
            return "left"
        if first in {b"l", b"L", b"d", b"D"}:
            return "right"
        if first in {b"x", b"X", b"t", b"T"}:
            return "space"
        if first in {b"+", b"="}:
            return "inc"
        if first in {b"-", b"_"}:
            return "dec"
        return None

    @staticmethod
    def read_escape_sequence(
        *,
        fd: int,
        selector: Callable[..., object],
        timeout: float,
        max_bytes: int,
    ) -> bytes:
        collected = bytearray()
        deadline = time.monotonic() + max(timeout, 0.0)
        while len(collected) < max_bytes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ready = cast(tuple[list[int], list[int], list[int]], selector([fd], [], [], remaining))
            readable = bool(ready and ready[0])
            if not readable:
                break
            chunk = os.read(fd, 1)
            if not chunk:
                break
            collected.extend(chunk)
            prefix = bytes(collected[:1])
            if prefix in {b"[", b"O"}:
                if chunk in {b"A", b"B", b"C", b"D", b"~", b"u"}:
                    break
                if len(collected) > 1 and re.fullmatch(rb"[A-Za-z]", chunk):
                    break
        return bytes(collected)

    @staticmethod
    def decode_escape(sequence: bytes) -> str | None:
        if not sequence:
            return None
        text = sequence.decode("latin-1", errors="ignore")
        if not text or text[0] not in {"[", "O"}:
            return None
        final = text[-1]
        mapping = {
            "A": "up",
            "B": "down",
            "C": "right",
            "D": "left",
        }
        if final not in mapping:
            return None
        if text[0] == "O":
            return mapping[final]
        body = text[1:-1]
        if not body or re.fullmatch(r"[0-9;]*", body):
            return mapping[final]
        return None

    @staticmethod
    def decode_modified_printable(sequence: bytes) -> str | None:
        if not sequence:
            return None
        text = sequence.decode("latin-1", errors="ignore")
        if len(text) == 1 and " " <= text <= "~":
            return text
        if not (text.startswith("[") and text.endswith("u")):
            return None
        body = text[1:-1]
        match = re.fullmatch(r"([0-9]{1,6})(?:;[0-9]{1,6})*", body)
        if not match:
            return None
        codepoint = int(match.group(1))
        if 32 <= codepoint <= 126:
            return chr(codepoint)
        return None

    def apply_key(
        self,
        *,
        key: str,
        cursor: int,
        planning_files: list[str],
        selected_counts: dict[str, int],
        existing_counts: dict[str, int],
    ) -> tuple[int, str, str]:
        if not planning_files:
            return cursor, "cancel", "No planning files available."

        max_index = len(planning_files) - 1
        cursor = max(0, min(cursor, max_index))
        current_plan = planning_files[cursor]

        if key == "up":
            return (cursor - 1) % len(planning_files), "continue", ""
        if key == "down":
            return (cursor + 1) % len(planning_files), "continue", ""
        if key in {"right", "inc"}:
            selected_counts[current_plan] = int(selected_counts.get(current_plan, 0)) + 1
            return cursor, "continue", ""
        if key in {"left", "dec"}:
            selected_counts[current_plan] = max(0, int(selected_counts.get(current_plan, 0)) - 1)
            return cursor, "continue", ""
        if key == "space":
            current = int(selected_counts.get(current_plan, 0))
            if current > 0:
                selected_counts[current_plan] = 0
            else:
                selected_counts[current_plan] = max(1, int(existing_counts.get(current_plan, 0)))
            return cursor, "continue", ""
        if key == "all":
            for plan_file in planning_files:
                selected_counts[plan_file] = max(1, int(selected_counts.get(plan_file, 0)))
            return cursor, "continue", ""
        if key == "none":
            for plan_file in planning_files:
                selected_counts[plan_file] = 0
            return cursor, "continue", ""
        if key == "enter":
            return cursor, "submit", ""
        if key in {"quit", "esc"}:
            return cursor, "cancel", ""
        return cursor, "continue", "Use arrows to navigate and adjust counts."

    @staticmethod
    def terminal_size() -> tuple[int, int]:
        size = shutil.get_terminal_size(fallback=(100, 24))
        width = max(40, int(getattr(size, "columns", 100)))
        height = max(10, int(getattr(size, "lines", 24)))
        return width, height

    @staticmethod
    def truncate_text(value: str, max_len: int) -> str:
        if max_len <= 0:
            return ""
        if len(value) <= max_len:
            return value
        if max_len <= 3:
            return "." * max_len
        return value[: max_len - 3] + "..."

    @staticmethod
    def to_terminal_lines(frame: str) -> str:
        return frame.replace("\n", "\r\n")

    @staticmethod
    def flush_pending_input(*, fd: int) -> None:
        import select as _select

        try:
            termios.tcflush(fd, termios.TCIFLUSH)
            return
        except Exception:
            pass

        drained = 0
        max_bytes = 4096
        while drained < max_bytes:
            ready, _, _ = _select.select([fd], [], [], 0)
            if not ready:
                break
            chunk = os.read(fd, 1)
            if not chunk:
                break
            drained += 1

    @staticmethod
    def _flush_input_buffer(*, fd: int) -> None:
        try:
            termios.tcflush(fd, termios.TCIFLUSH)
            return
        except Exception:
            pass
        try:
            PlanningSelectionMenu.flush_pending_input(fd=fd)
        except Exception:
            pass

    @staticmethod
    def _restore_terminal_state(*, fd: int, original_state: Any) -> None:
        for mode in (termios.TCSADRAIN, termios.TCSAFLUSH):
            try:
                termios.tcsetattr(fd, mode, original_state)
                return
            except Exception:
                continue
        try:
            subprocess.run(
                ["stty", "sane"],
                stdin=fd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            return
