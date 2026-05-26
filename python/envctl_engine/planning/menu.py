from __future__ import annotations

import os
import select
import sys
import termios
import tty
from dataclasses import dataclass
from typing import Any, Callable

from envctl_engine.planning.menu_input import (
    decode_escape as decode_escape_sequence,
    decode_modified_printable,
    flush_input_buffer,
    flush_pending_input as flush_pending_menu_input,
    map_single_byte_key,
    read_escape_sequence,
    read_planning_menu_key,
    restore_terminal_state,
)
from envctl_engine.planning.menu_rendering import (
    render_planning_selection_menu,
    terminal_size as planning_terminal_size,
    to_terminal_lines,
    truncate_text,
)
from envctl_engine.planning.menu_selection import apply_planning_menu_key, submitted_planning_counts
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
                    return PlanningMenuResult(
                        selected_counts=submitted_planning_counts(
                            planning_files=planning_files,
                            selected_counts=selected_counts,
                            existing_counts=existing_counts,
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
                event.app.exit(
                    result=PlanningMenuResult(
                        selected_counts=submitted_planning_counts(
                            planning_files=planning_files,
                            selected_counts=selected_counts,
                            existing_counts=existing_counts,
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
        return render_planning_selection_menu(
            planning_files=planning_files,
            selected_counts=selected_counts,
            existing_counts=existing_counts,
            cursor=cursor,
            message=message,
            terminal_width=terminal_width,
            terminal_height=terminal_height,
        )

    @staticmethod
    def read_key(*, fd: int, selector: Callable[..., object]) -> str:
        return read_planning_menu_key(fd=fd, selector=selector)

    @staticmethod
    def _map_single_byte_key(first: bytes) -> str | None:
        return map_single_byte_key(first)

    @staticmethod
    def read_escape_sequence(
        *,
        fd: int,
        selector: Callable[..., object],
        timeout: float,
        max_bytes: int,
    ) -> bytes:
        return read_escape_sequence(fd=fd, selector=selector, timeout=timeout, max_bytes=max_bytes)

    @staticmethod
    def decode_escape(sequence: bytes) -> str | None:
        return decode_escape_sequence(sequence)

    @staticmethod
    def decode_modified_printable(sequence: bytes) -> str | None:
        return decode_modified_printable(sequence)

    @staticmethod
    def apply_key(
        *,
        key: str,
        cursor: int,
        planning_files: list[str],
        selected_counts: dict[str, int],
        existing_counts: dict[str, int],
    ) -> tuple[int, str, str]:
        return apply_planning_menu_key(
            key=key,
            cursor=cursor,
            planning_files=planning_files,
            selected_counts=selected_counts,
            existing_counts=existing_counts,
        )

    @staticmethod
    def terminal_size() -> tuple[int, int]:
        return planning_terminal_size()

    @staticmethod
    def truncate_text(value: str, max_len: int) -> str:
        return truncate_text(value, max_len)

    @staticmethod
    def to_terminal_lines(frame: str) -> str:
        return to_terminal_lines(frame)

    @staticmethod
    def flush_pending_input(*, fd: int) -> None:
        flush_pending_menu_input(fd=fd)

    @staticmethod
    def _flush_input_buffer(*, fd: int) -> None:
        flush_input_buffer(fd=fd, fallback_flush=PlanningSelectionMenu.flush_pending_input)

    @staticmethod
    def _restore_terminal_state(*, fd: int, original_state: Any) -> None:
        restore_terminal_state(fd=fd, original_state=original_state)
