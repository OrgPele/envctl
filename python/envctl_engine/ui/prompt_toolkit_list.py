from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import os
import sys
import time
from typing import Callable, Sequence, cast

from envctl_engine.ui.selector_model import SelectorItem


@dataclass(slots=True)
class PromptToolkitListResult:
    values: list[str] | None
    cancelled: bool


@dataclass(slots=True)
class PromptToolkitListConfig:
    prompt: str
    options: Sequence[SelectorItem]
    multi: bool
    selector_id: str
    backend_label: str
    screen_name: str
    focused_widget_id: str
    deep_debug: bool
    driver_trace_enabled: bool
    wrap_navigation: bool
    cancel_on_escape: bool
    initial_tokens: Sequence[str] | None = None
    emit_event: Callable[[str, object], None] | None = None
    emit_debug: Callable[[str, object], None] | None = None
    row_text: Callable[[SelectorItem], str] | None = None
    help_text_multi: str = "UP/DOWN or j/k move  Space toggle  a/Ctrl+A all  Enter submit  q/Esc cancel"
    help_text_single: str = "UP/DOWN or j/k move  Enter submit  Space select  q/Esc cancel"
    confirm_cause: str = "enter"
    cancel_cause: str = "cancel_key"
    record_raw_keys: bool = True


def create_prompt_toolkit_tty_io(*, stack: ExitStack) -> tuple[object, object, str]:
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


def run_prompt_toolkit_list_selector(
    config: PromptToolkitListConfig,
) -> PromptToolkitListResult | None:
    status_error_timeout_seconds = 3.0
    rows = [item for item in config.options if bool(getattr(item, "enabled", True))]
    if not rows:
        return PromptToolkitListResult(values=[], cancelled=False)

    try:
        from prompt_toolkit.application import Application
        from prompt_toolkit.formatted_text import ANSI
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import Window
        from prompt_toolkit.layout.controls import FormattedTextControl
    except Exception:
        return None

    no_color = bool(os.environ.get("NO_COLOR"))
    reset = "" if no_color else "\033[0m"
    bold = "" if no_color else "\033[1m"
    dim = "" if no_color else "\033[2m"
    cyan = "" if no_color else "\033[36m"
    magenta = "" if no_color else "\033[35m"
    green = "" if no_color else "\033[32m"
    red = "" if no_color else "\033[31m"

    def _emit_event(event: str, **payload: object) -> None:
        if callable(config.emit_event):
            config.emit_event(event, **payload)

    def _emit_debug(event: str, **payload: object) -> None:
        if callable(config.emit_debug):
            config.emit_debug(event, **payload)

    initial_token_set = {str(token).strip() for token in (config.initial_tokens or []) if str(token).strip()}
    cursor = 0
    selected_indexes: set[int] = set()
    if initial_token_set:
        if config.multi:
            selected_indexes = {
                index for index, item in enumerate(rows) if str(getattr(item, "token", "")).strip() in initial_token_set
            }
        for index, item in enumerate(rows):
            if str(getattr(item, "token", "")).strip() in initial_token_set:
                cursor = index
                if not config.multi:
                    selected_indexes = {index}
                break

    key_counts: dict[str, int] = {}
    handled_counts: dict[str, int] = {}
    unhandled_counts: dict[str, int] = {}
    key_events_total = 0
    io_probe: Callable[[], dict[str, object]] | None = None
    status_error = ""
    status_error_deadline = 0.0

    _emit_event(
        "ui.screen.enter",
        screen=config.screen_name,
        prompt=config.prompt,
        option_count=len(rows),
        multi=config.multi,
    )
    _emit_debug(
        "ui.selector.lifecycle",
        selector_id=config.selector_id,
        prompt=config.prompt,
        option_count=len(rows),
        multi=config.multi,
        phase="enter",
        backend=config.backend_label,
        ts_mono_ns=time.monotonic_ns(),
    )

    def _row_text(item: SelectorItem) -> str:
        if callable(config.row_text):
            return config.row_text(item)
        badge = str(getattr(item, "kind", "target") or "target").replace("_", " ")
        label = str(getattr(item, "label", "") or "").strip() or str(getattr(item, "token", "target"))
        return f"{label} ({badge})"

    def _frame() -> ANSI:
        nonlocal status_error, status_error_deadline
        if status_error and status_error_deadline > 0.0 and time.monotonic() >= status_error_deadline:
            status_error = ""
            status_error_deadline = 0.0
        lines = [f"{bold}{cyan}{config.prompt}{reset}"]
        lines.append(f"{dim}{config.help_text_multi if config.multi else config.help_text_single}{reset}")
        if status_error:
            lines.append(f"{bold}{red}{status_error}{reset}")
        lines.append("")
        last_section = ""
        for index, item in enumerate(rows):
            section = str(getattr(item, "section", "") or "").strip()
            if section and section != last_section:
                lines.append(f"{bold}{section}{reset}")
                last_section = section
            pointer = f"{magenta}▶{reset}" if index == cursor else " "
            marker = f"{green}●{reset}" if index in selected_indexes else "○"
            lines.append(f"{pointer} {marker} {_row_text(item)}")
        return ANSI("\n".join(lines))

    def _emit_key(key: str, before: int, after: int, *, handled: bool) -> None:
        nonlocal key_events_total, status_error_deadline
        key_counts[key] = int(key_counts.get(key, 0)) + 1
        key_events_total += 1
        if status_error:
            status_error_deadline = time.monotonic() + status_error_timeout_seconds
        target = handled_counts if handled else unhandled_counts
        target[key] = int(target.get(key, 0)) + 1
        _emit_debug(
            "ui.selector.key",
            selector_id=config.selector_id,
            key=key,
            focused_widget_id=config.focused_widget_id,
            list_index_before=before,
            list_index_after=after,
            handled=handled,
        )

    def _toggle_current(key_name: str, event: object) -> None:
        nonlocal selected_indexes, status_error, status_error_deadline
        before = cursor
        status_error = ""
        status_error_deadline = 0.0
        if config.multi:
            if cursor in selected_indexes:
                selected_indexes.remove(cursor)
                selected = False
            else:
                selected_indexes.add(cursor)
                selected = True
        else:
            selected_indexes = {cursor}
            selected = True
        _emit_event("ui.selection.toggle", token=str(rows[cursor].token), selected=selected)
        _emit_key(key_name, before, cursor, handled=True)
        event.app.invalidate()  # type: ignore[attr-defined]

    def _toggle_all(event: object) -> None:
        nonlocal selected_indexes, status_error, status_error_deadline
        before = cursor
        status_error = ""
        status_error_deadline = 0.0
        if not config.multi:
            selected_indexes = {cursor}
            _emit_key("ctrl+a", before, cursor, handled=True)
            event.app.invalidate()  # type: ignore[attr-defined]
            return
        should_select = any(index not in selected_indexes for index in range(len(rows)))
        selected_indexes = set(range(len(rows))) if should_select else set()
        _emit_event("ui.selection.toggle", token="__VISIBLE__", selected=should_select)
        _emit_key("ctrl+a", before, cursor, handled=True)
        event.app.invalidate()  # type: ignore[attr-defined]

    def _move(delta: int, key_name: str, event: object) -> None:
        nonlocal cursor
        before = cursor
        if config.wrap_navigation:
            cursor = (cursor + delta) % len(rows)
        else:
            cursor = max(0, min(len(rows) - 1, cursor + delta))
        _emit_key(key_name, before, cursor, handled=True)
        event.app.invalidate()  # type: ignore[attr-defined]

    def _submit(event: object) -> None:
        nonlocal selected_indexes, status_error, status_error_deadline
        if config.multi and not selected_indexes:
            status_error = "No items were selected. Press Space or click to select at least one."
            status_error_deadline = time.monotonic() + status_error_timeout_seconds
            _emit_event(
                "ui.selection.confirm",
                prompt=config.prompt,
                multi=config.multi,
                selected_count=0,
                blocked=True,
            )
            _emit_debug(
                "ui.selector.submit",
                selector_id=config.selector_id,
                selected_count=0,
                blocked=True,
                cancelled=False,
                cause=config.confirm_cause,
            )
            event.app.invalidate()  # type: ignore[attr-defined]
            return
        if not selected_indexes:
            status_error = ""
            status_error_deadline = 0.0
            selected_indexes = {cursor}
            _emit_event("ui.selection.toggle", token=str(rows[cursor].token), selected=True)
        values = [str(rows[index].token) for index in sorted(selected_indexes)]
        _emit_event(
            "ui.selection.confirm",
            prompt=config.prompt,
            multi=config.multi,
            selected_count=len(values),
        )
        _emit_debug(
            "ui.selector.submit",
            selector_id=config.selector_id,
            selected_count=len(values),
            blocked=False,
            cancelled=False,
            cause=config.confirm_cause,
        )
        event.app.exit(result=PromptToolkitListResult(values=values, cancelled=False))  # type: ignore[attr-defined]

    def _cancel(event: object) -> None:
        _emit_event("ui.selection.cancel", prompt=config.prompt, multi=config.multi)
        _emit_debug(
            "ui.selector.submit",
            selector_id=config.selector_id,
            selected_count=0,
            blocked=False,
            cancelled=True,
            cause=config.cancel_cause,
        )
        event.app.exit(result=PromptToolkitListResult(values=None, cancelled=True))  # type: ignore[attr-defined]

    bindings = KeyBindings()
    for key_name in ("up", "k", "w"):
        bindings.add(key_name)(lambda event, _key=key_name: _move(-1, _key, event))
    for key_name in ("down", "j", "s"):
        bindings.add(key_name)(lambda event, _key=key_name: _move(1, _key, event))
    bindings.add(" ")(lambda event: _toggle_current("space", event))
    bindings.add("x")(lambda event: _toggle_current("x", event))
    bindings.add("a")(_toggle_all)
    bindings.add("c-a")(_toggle_all)
    bindings.add("enter")(_submit)
    if config.cancel_on_escape:
        bindings.add("escape")(_cancel)
    else:
        bindings.add("escape")(lambda event: _emit_key("escape", cursor, cursor, handled=True))
    bindings.add("q")(_cancel)
    bindings.add("c-c")(_cancel)

    with ExitStack() as stack:
        from envctl_engine.ui.textual.screens.selector.support import _instrument_prompt_toolkit_posix_io

        ptk_input, ptk_output, io_source = create_prompt_toolkit_tty_io(stack=stack)
        app = Application(
            layout=Layout(Window(content=FormattedTextControl(text=_frame, focusable=False))),
            key_bindings=bindings,
            full_screen=True,
            input=ptk_input,
            output=ptk_output,
            refresh_interval=0.25,
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
        _emit_debug(
            "ui.selector.key.timeout",
            selector_id=config.selector_id,
            backend=config.backend_label,
            timeout_ms=timeout_ms,
            ttimeout_ms=ttimeout_ms,
        )
        if config.record_raw_keys:
            key_processor = getattr(app, "key_processor", None)
            before_key_press = getattr(key_processor, "before_key_press", None)
            if before_key_press is not None:

                def _record_raw_key(key_press: object) -> None:
                    key_name = str(getattr(key_press, "key", "") or "unknown")
                    key_data = str(getattr(key_press, "data", "") or "")
                    _emit_key(key_name, cursor, cursor, handled=False)
                    _emit_debug(
                        "ui.selector.key.raw",
                        selector_id=config.selector_id,
                        key=key_name,
                        data_repr=repr(key_data),
                        focused_widget_id=config.focused_widget_id,
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
        _emit_debug(
            "ui.selector.key.driver.config",
            selector_id=config.selector_id,
            backend=config.backend_label,
            io_source=io_source,
            input_class=type(app_input).__name__ if app_input is not None else "none",
            stdin_tty=bool(getattr(sys.stdin, "isatty", lambda: False)()),
            stdout_tty=bool(getattr(sys.stdout, "isatty", lambda: False)()),
            term=str(os.environ.get("TERM", "")),
            **tty_mode,
        )
        try:
            with _instrument_prompt_toolkit_posix_io(
                emit=None,
                deep_debug=config.deep_debug,
                enabled=config.driver_trace_enabled,
                selector_id=config.selector_id,
            ) as ptk_probe_tuple:
                io_probe = ptk_probe_tuple[0]
                result = app.run()
        except (EOFError, KeyboardInterrupt):
            result = PromptToolkitListResult(values=None, cancelled=True)
        finally:
            io_stats = io_probe() if callable(io_probe) else {}
            io_read_calls = int(io_stats.get("io_read_calls", 0))
            io_read_errors = int(io_stats.get("io_read_errors", 0))
            io_read_samples = list(cast(list[str], io_stats.get("io_read_samples", [])))
            _emit_debug(
                "ui.selector.key.driver.summary",
                selector_id=config.selector_id,
                backend=config.backend_label,
                read_calls=io_read_calls,
                read_errors=io_read_errors,
                key_events_total=key_events_total,
                key_events_by_name=dict(key_counts),
                read_samples=io_read_samples,
                handled_counts=dict(handled_counts),
                unhandled_counts=dict(unhandled_counts),
                **io_stats,
            )

    _emit_debug(
        "ui.selector.key.summary",
        selector_id=config.selector_id,
        handled_counts=dict(handled_counts),
        raw_counts=dict(unhandled_counts),
        event_counts=dict(key_counts),
    )
    _emit_debug(
        "ui.selector.lifecycle",
        selector_id=config.selector_id,
        prompt=config.prompt,
        option_count=len(rows),
        multi=config.multi,
        phase="exit",
        backend=config.backend_label,
        ts_mono_ns=time.monotonic_ns(),
    )
    _emit_event("ui.screen.exit", screen=config.screen_name, prompt=config.prompt)

    if isinstance(result, PromptToolkitListResult):
        return result
    if hasattr(result, "values") and hasattr(result, "cancelled"):
        return PromptToolkitListResult(
            values=getattr(result, "values"),
            cancelled=bool(getattr(result, "cancelled")),
        )
    return PromptToolkitListResult(values=None, cancelled=True)
