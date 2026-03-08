from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import os
import sys
import time
from typing import Callable, cast, Sequence

from .selector_model import SelectorItem


@dataclass(slots=True)
class CursorMenuResult:
    values: list[str] | None
    cancelled: bool


def _emit(emit: Callable[..., None] | None, event: str, **payload: object) -> None:
    if callable(emit):
        emit(event, component="ui.prompt_toolkit_cursor_menu", **payload)


def _create_prompt_toolkit_tty_io(*, stack: ExitStack) -> tuple[object, object, str]:
    from prompt_toolkit.input.defaults import create_input
    from prompt_toolkit.output.defaults import create_output

    source = "auto_tty"
    try:
        if sys.stdin.isatty():
            source = "auto_tty_stdin"
        elif sys.stdout.isatty():
            source = "auto_tty_stdout"
        elif sys.stderr.isatty():
            source = "auto_tty_stderr"
    except Exception:
        source = "auto_tty"
    ptk_input = create_input(always_prefer_tty=True)
    ptk_output = create_output(always_prefer_tty=True)
    close_input = getattr(ptk_input, "close", None)
    if callable(close_input):
        stack.callback(close_input)
    close_output = getattr(ptk_output, "close", None)
    if callable(close_output):
        stack.callback(close_output)
    return ptk_input, ptk_output, source


def run_prompt_toolkit_cursor_menu(
    *,
    prompt: str,
    options: Sequence[SelectorItem],
    multi: bool,
    initial_tokens: Sequence[str] | None = None,
    emit: Callable[..., None] | None = None,
    selector_id: str,
    deep_debug: bool,
) -> CursorMenuResult | None:
    rows = [item for item in options if bool(getattr(item, "enabled", True))]
    if not rows:
        return CursorMenuResult(values=[], cancelled=False)

    try:
        from prompt_toolkit.application import Application
        from prompt_toolkit.formatted_text import ANSI
        from prompt_toolkit.input.defaults import create_input
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.output.defaults import create_output
    except Exception:
        return None
    from envctl_engine.ui.textual.screens.selector.support import (
        _emit_selector_debug,
        _instrument_prompt_toolkit_posix_io,
    )

    no_color = bool(os.environ.get("NO_COLOR"))
    reset = "" if no_color else "\033[0m"
    bold = "" if no_color else "\033[1m"
    dim = "" if no_color else "\033[2m"
    cyan = "" if no_color else "\033[36m"
    magenta = "" if no_color else "\033[35m"
    green = "" if no_color else "\033[32m"

    cursor = 0
    selected_indexes: set[int] = set()
    initial_token_set = {str(token).strip() for token in (initial_tokens or []) if str(token).strip()}
    if initial_token_set:
        if multi:
            selected_indexes = {
                idx for idx, item in enumerate(rows) if str(getattr(item, "token", "")).strip() in initial_token_set
            }
        for idx, item in enumerate(rows):
            if str(getattr(item, "token", "")).strip() in initial_token_set:
                cursor = idx
                if not multi:
                    selected_indexes = {idx}
                break
    key_counts: dict[str, int] = {}
    handled_counts: dict[str, int] = {}
    unhandled_counts: dict[str, int] = {}
    key_events_total = 0
    ptk_io_probe: Callable[[], dict[str, object]] | None = None

    _emit(
        emit,
        "ui.screen.enter",
        screen="selector_prompt_toolkit_cursor",
        prompt=prompt,
        option_count=len(rows),
        multi=multi,
    )
    if deep_debug:
        _emit(
            emit,
            "ui.selector.lifecycle",
            selector_id=selector_id,
            prompt=prompt,
            option_count=len(rows),
            multi=multi,
            phase="enter",
            backend="planning_style_prompt_toolkit",
            ts_mono_ns=time.monotonic_ns(),
        )

    def _row_text(item: SelectorItem) -> str:
        badge = str(getattr(item, "kind", "target") or "target").replace("_", " ")
        label = str(getattr(item, "label", "") or "").strip() or str(getattr(item, "token", "target"))
        return f"{label} ({badge})"

    def _frame() -> ANSI:
        lines: list[str] = [f"{bold}{cyan}{prompt}{reset}"]
        lines.append(
            f"{dim}UP/DOWN or j/k/w/s move  Space/x toggle  Enter submit  q/Esc/Ctrl+C cancel{reset}"
            if multi
            else f"{dim}UP/DOWN or j/k/w/s move  Space/x select  Enter submit  q/Esc/Ctrl+C cancel{reset}"
        )
        lines.append("")
        last_section = ""
        for idx, item in enumerate(rows):
            section = str(getattr(item, "section", "") or "").strip()
            if section and section != last_section:
                lines.append(f"{bold}{section}{reset}")
                last_section = section
            pointer = f"{magenta}▶{reset}" if idx == cursor else " "
            marker = f"{green}●{reset}" if idx in selected_indexes else "○"
            lines.append(f"{pointer} {marker} {_row_text(item)}")
        return ANSI("\n".join(lines))

    def _emit_key(key: str, before: int, after: int, *, handled: bool) -> None:
        nonlocal key_events_total
        key_counts[key] = int(key_counts.get(key, 0)) + 1
        key_events_total += 1
        target = handled_counts if handled else unhandled_counts
        target[key] = int(target.get(key, 0)) + 1
        if deep_debug:
            _emit(
                emit,
                "ui.selector.key",
                selector_id=selector_id,
                key=key,
                focused_widget_id="selector-prompt-toolkit-cursor",
                list_index_before=before,
                list_index_after=after,
                handled=handled,
            )

    def _toggle_current(key: str, event: object) -> None:
        nonlocal selected_indexes
        before = cursor
        if multi:
            if cursor in selected_indexes:
                selected_indexes.remove(cursor)
                selected = False
            else:
                selected_indexes.add(cursor)
                selected = True
        else:
            selected_indexes = {cursor}
            selected = True
        _emit(emit, "ui.selection.toggle", token=str(rows[cursor].token), selected=selected)
        _emit_key(key, before, cursor, handled=True)
        event.app.invalidate()  # type: ignore[attr-defined]

    def _move(delta: int, key: str, event: object) -> None:
        nonlocal cursor
        before = cursor
        cursor = (cursor + delta) % len(rows)
        _emit_key(key, before, cursor, handled=True)
        event.app.invalidate()  # type: ignore[attr-defined]

    def _submit(event: object) -> None:
        nonlocal selected_indexes
        if not selected_indexes:
            selected_indexes = {cursor}
            _emit(emit, "ui.selection.toggle", token=str(rows[cursor].token), selected=True)
        values = [str(rows[idx].token) for idx in sorted(selected_indexes)]
        _emit(emit, "ui.selection.confirm", prompt=prompt, multi=multi, selected_count=len(values))
        if deep_debug:
            _emit(
                emit,
                "ui.selector.submit",
                selector_id=selector_id,
                selected_count=len(values),
                blocked=False,
                cancelled=False,
                cause="enter",
            )
        event.app.exit(result=CursorMenuResult(values=values, cancelled=False))  # type: ignore[attr-defined]

    def _cancel(event: object) -> None:
        _emit(emit, "ui.selection.cancel", prompt=prompt, multi=multi)
        if deep_debug:
            _emit(
                emit,
                "ui.selector.submit",
                selector_id=selector_id,
                selected_count=0,
                blocked=False,
                cancelled=True,
                cause="cancel_key",
            )
        event.app.exit(result=CursorMenuResult(values=None, cancelled=True))  # type: ignore[attr-defined]

    bindings = KeyBindings()
    for key in ("up", "k", "w"):
        bindings.add(key)(lambda event, _k=key: _move(-1, _k, event))
    for key in ("down", "j", "s"):
        bindings.add(key)(lambda event, _k=key: _move(1, _k, event))
    bindings.add(" ")(lambda event: _toggle_current("space", event))
    bindings.add("x")(lambda event: _toggle_current("x", event))
    bindings.add("enter")(_submit)
    bindings.add("escape")(_cancel)
    bindings.add("q")(_cancel)
    bindings.add("c-c")(_cancel)

    with ExitStack() as stack:
        ptk_input, ptk_output, io_source = _create_prompt_toolkit_tty_io(stack=stack)
        app = Application(
            layout=Layout(Window(content=FormattedTextControl(text=_frame, focusable=False))),
            key_bindings=bindings,
            full_screen=True,
            input=ptk_input,
            output=ptk_output,
        )
        selector_timeout_ms_raw = str(os.environ.get("ENVCTL_UI_SELECTOR_TIMEOUT_MS", "")).strip()
        selector_ttimeout_ms_raw = str(os.environ.get("ENVCTL_UI_SELECTOR_TTIMEOUT_MS", "")).strip()
        try:
            timeout_ms = int(selector_timeout_ms_raw) if selector_timeout_ms_raw else 1000
        except ValueError:
            timeout_ms = 1000
        try:
            ttimeout_ms = int(selector_ttimeout_ms_raw) if selector_ttimeout_ms_raw else 1400
        except ValueError:
            ttimeout_ms = 1400
        timeout_ms = max(50, min(5000, timeout_ms))
        ttimeout_ms = max(50, min(5000, ttimeout_ms))
        try:
            app.timeoutlen = float(timeout_ms) / 1000.0
        except Exception:
            pass
        try:
            app.ttimeoutlen = float(ttimeout_ms) / 1000.0
        except Exception:
            pass
        _emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.timeout",
            selector_id=selector_id,
            backend="planning_style_prompt_toolkit",
            timeout_ms=timeout_ms,
            ttimeout_ms=ttimeout_ms,
        )
        key_processor = getattr(app, "key_processor", None)
        before_key_press = getattr(key_processor, "before_key_press", None)
        if before_key_press is not None:
            def _record_raw_key(key_press: object) -> None:
                key_name = str(getattr(key_press, "key", "") or "unknown")
                key_data = str(getattr(key_press, "data", "") or "")
                _emit_key(key_name, cursor, cursor, handled=False)
                _emit_selector_debug(
                    emit,
                    enabled=deep_debug,
                    event="ui.selector.key.raw",
                    selector_id=selector_id,
                    key=key_name,
                    data_repr=repr(key_data),
                    focused_widget_id="selector-prompt-toolkit-cursor",
                    list_index_before=cursor,
                    list_index_after=cursor,
                    handled=False,
                )
            try:
                before_key_press += _record_raw_key
            except Exception:
                pass
        app_input = getattr(app, "input", None)
        stdin_fd: int | None = None
        try:
            stdin_reader = getattr(app_input, "stdin_reader", None)
            if stdin_reader is not None:
                stdin_fd_raw = getattr(stdin_reader, "stdin_fd", None)
                if isinstance(stdin_fd_raw, int):
                    stdin_fd = stdin_fd_raw
            if stdin_fd is None:
                fileno_raw = getattr(app_input, "_fileno", None)
                if isinstance(fileno_raw, int):
                    stdin_fd = fileno_raw
        except Exception:
            stdin_fd = None
        tty_mode: dict[str, object] = {}
        if isinstance(stdin_fd, int):
            try:
                import termios
                attrs = termios.tcgetattr(stdin_fd)
                lflag = int(attrs[3])
                tty_mode = {
                    "stdin_fd": stdin_fd,
                    "tty_lflag": lflag,
                    "tty_canonical": bool(lflag & int(termios.ICANON)),
                    "tty_echo": bool(lflag & int(termios.ECHO)),
                    "tty_isig": bool(lflag & int(termios.ISIG)),
                }
            except Exception:
                tty_mode = {"stdin_fd": stdin_fd, "tty_mode_error": True}
        _emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.config",
            selector_id=selector_id,
            backend="planning_style_prompt_toolkit",
            io_source=io_source,
            input_class=type(app_input).__name__ if app_input is not None else "none",
            stdin_tty=bool(getattr(sys.stdin, "isatty", lambda: False)()),
            stdout_tty=bool(getattr(sys.stdout, "isatty", lambda: False)()),
            term=str(os.environ.get("TERM", "")),
            **tty_mode,
        )
        try:
            with _instrument_prompt_toolkit_posix_io(
                emit=emit,
                deep_debug=deep_debug,
                enabled=deep_debug,
                selector_id=selector_id,
            ) as ptk_probe_tuple:
                ptk_io_probe = ptk_probe_tuple[0]
                result = app.run()
        except (EOFError, KeyboardInterrupt):
            result = CursorMenuResult(values=None, cancelled=True)
        finally:
            io_stats = ptk_io_probe() if callable(ptk_io_probe) else {}
            io_read_calls = int(io_stats.get("io_read_calls", 0))
            io_read_errors = int(io_stats.get("io_read_errors", 0))
            io_read_samples = list(cast(list[str], io_stats.get("io_read_samples", [])))
            _emit_selector_debug(
                emit,
                enabled=deep_debug,
                event="ui.selector.key.driver.summary",
                selector_id=selector_id,
                backend="planning_style_prompt_toolkit",
                read_calls=io_read_calls,
                read_errors=io_read_errors,
                key_events_total=key_events_total,
                key_events_by_name=dict(key_counts),
                read_samples=io_read_samples,
                handled_counts=dict(handled_counts),
                unhandled_counts=dict(unhandled_counts),
                **io_stats,
            )

    if deep_debug:
        _emit(
            emit,
            "ui.selector.key.summary",
            selector_id=selector_id,
            handled_counts=dict(handled_counts),
            raw_counts=dict(unhandled_counts),
            event_counts=dict(key_counts),
        )
        _emit(
            emit,
            "ui.selector.lifecycle",
            selector_id=selector_id,
            prompt=prompt,
            option_count=len(rows),
            multi=multi,
            phase="exit",
            backend="planning_style_prompt_toolkit",
            ts_mono_ns=time.monotonic_ns(),
        )
    _emit(emit, "ui.screen.exit", screen="selector_prompt_toolkit_cursor", prompt=prompt)

    if isinstance(result, CursorMenuResult):
        return result
    return CursorMenuResult(values=None, cancelled=True)
