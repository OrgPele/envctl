from __future__ import annotations

import shlex
import uuid
from contextlib import redirect_stdout
from dataclasses import dataclass
from io import StringIO
from typing import Any, Callable

try:
    from rich.text import Text as _RichText
except Exception:  # pragma: no cover - exercised in minimal dependency environments
    _RichText = None

from ...debug.debug_utils import hash_command
from ...state.models import RunState
from ..command_aliases import normalize_interactive_command
from ..capabilities import textual_importable as _textual_importable
from .compat import apply_textual_driver_compat, textual_run_policy
from .state_bridge import render_dashboard_snapshot


@dataclass(frozen=True, slots=True)
class _PlainRenderable:
    plain: str

    def __str__(self) -> str:
        return self.plain

def _emit(runtime: Any, event: str, **payload: object) -> None:
    candidate = getattr(runtime, "_emit", None)
    if callable(candidate):
        candidate(event, component="ui.textual.dashboard", **payload)


def _to_renderable(value: str) -> object:
    text = str(value or "")
    if _RichText is None:
        return _PlainRenderable(plain=text)
    return _RichText.from_ansi(text)


def _dashboard_commands_help() -> str:
    return (
        "Commands: (q)uit\n"
        "  Lifecycle: (s)top | (r)estart | stop-all | blast-all\n"
        "  Actions: (t)est | (p)r | (c)ommit | (a)nalyze | (m)igrate\n"
        "  Inspect: (l)ogs | (h)ealth | (e)rrors | confi(g)"
    )


def _normalize_dashboard_command(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        tokens = shlex.split(text)
    except ValueError:
        return text
    if not tokens:
        return ""
    command = tokens[0].strip().lower()
    return normalize_interactive_command(command)


def _route_key_to_command_input(
    *,
    key: str,
    character: str | None,
    is_printable: bool,
    focused_input: bool,
    current_value: str,
    dispatch_in_flight: bool,
) -> tuple[bool, str, bool, bool]:
    if dispatch_in_flight or focused_input:
        return False, current_value, False, False
    normalized_key = str(key or "").strip().lower()
    if normalized_key in {"enter", "return"}:
        has_value = bool(str(current_value or "").strip())
        return True, current_value, True, has_value
    if normalized_key in {"backspace", "delete"}:
        if not current_value:
            return True, current_value, True, False
        return True, current_value[:-1], True, False
    if is_printable and character and character not in {"\r", "\n"}:
        return True, f"{current_value}{character}", True, False
    return False, current_value, False, False


def run_textual_dashboard_loop(
    *,
    state: RunState,
    runtime: Any,
    handle_command: Callable[[str, RunState], tuple[bool, RunState]],
    sanitize: Callable[[str], str],
) -> int:
    if not _textual_importable():
        _emit(runtime, "ui.fallback.non_interactive", reason="textual_missing", command="dashboard")
        runtime._print_dashboard_snapshot(state)
        return 0
    run_policy = textual_run_policy(screen="dashboard")

    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Vertical
    from textual.widgets import Footer, Input, Static

    class DashboardApp(App[int]):
        BINDINGS = [
            Binding("ctrl+c", "quit", "Quit"),
            Binding("escape", "quit", "Quit"),
        ]
        CSS = """
        Screen {
            align: center middle;
        }
        #shell {
            width: 95%;
            height: 95%;
            border: round $accent;
            padding: 1;
        }
        #title {
            text-style: bold;
            margin-bottom: 1;
        }
        #snapshot {
            height: 1fr;
            border: round $surface;
            padding: 0 1;
            overflow: auto;
        }
        #status {
            height: 3;
            border: round $surface;
            padding: 0 1;
            margin-top: 1;
        }
        #commands {
            height: auto;
            border: round $surface;
            padding: 0 1;
            margin-top: 1;
        }
        #command {
            margin-top: 1;
        }
        """

        def __init__(self) -> None:
            super().__init__()
            self.current_state = state
            self._dispatch_in_flight = False

        def compose(self) -> ComposeResult:
            with Vertical(id="shell"):
                yield Static("Development Environment - Interactive Mode (Textual)", id="title")
                yield Static("", id="snapshot")
                yield Static(_dashboard_commands_help(), id="commands")
                yield Static("Type command and press Enter. q to quit.", id="status")
                yield Input(placeholder="Enter command", id="command")
                yield Footer()

        def on_mount(self) -> None:
            _emit(runtime, "ui.screen.enter", screen="dashboard")
            try:
                apply_textual_driver_compat(
                    driver=getattr(self.app, "_driver", None),
                    screen="dashboard",
                    mouse_enabled=run_policy.mouse,
                    disable_focus_reporting=True,
                    emit=lambda event, **payload: _emit(runtime, event, **payload),
                )
            except Exception:
                pass
            self._refresh_snapshot()
            self._focus_command_input(reason="mount")

        def _refresh_snapshot(self) -> None:
            text = render_dashboard_snapshot(runtime=runtime, state=self.current_state)
            self.query_one("#snapshot", Static).update(_to_renderable(text or "(no services)"))

        def _set_status(self, text: str) -> None:
            self.query_one("#status", Static).update(_to_renderable(text))

        def _focus_command_input(self, *, reason: str) -> None:
            command_input = self.query_one("#command", Input)
            command_input.focus()
            _emit(runtime, "ui.input.focus.changed", focused=True, reason=reason)

        def _set_command_input_enabled(self, enabled: bool, *, reason: str) -> None:
            command_input = self.query_one("#command", Input)
            command_input.disabled = not enabled
            _emit(runtime, "ui.input.focus.changed", focused=enabled, reason=reason)

        async def _submit_command(self, *, raw: str, source: str) -> None:
            sanitized = sanitize(raw)
            if not sanitized:
                self._set_status("Ignored empty command.")
                self._focus_command_input(reason="empty_command")
                return

            command_id = f"cmd-{uuid.uuid4().hex[:12]}"
            salt = str(getattr(runtime, "_debug_hash_salt", "interactive"))
            command_hash, command_length = hash_command(sanitized, salt)
            normalized_command = _normalize_dashboard_command(sanitized)
            _emit(
                runtime,
                "ui.input.submit",
                command_id=command_id,
                command_hash=command_hash,
                command_length=command_length,
                normalized_command=normalized_command,
                source=source,
            )
            _emit(runtime, "ui.input.submit.accepted", command_id=command_id, normalized_command=normalized_command)
            _emit(runtime, "ui.command.dispatch.begin", command_id=command_id)
            self._dispatch_in_flight = True
            self._set_command_input_enabled(False, reason="dispatch_begin")
            out = StringIO()
            try:
                with redirect_stdout(out):
                    should_continue, new_state = handle_command(sanitized, self.current_state)
            except Exception as exc:
                _emit(runtime, "ui.command.dispatch.end", command_id=command_id, failed=True, error=str(exc))
                self._set_status(f"Command failed: {exc}")
                should_continue = True
            else:
                self.current_state = new_state
                _emit(runtime, "ui.command.dispatch.end", command_id=command_id, failed=False)
                rendered = out.getvalue().strip()
                if rendered:
                    self._set_status(rendered[-300:])
                else:
                    self._set_status("Command complete.")
                self._refresh_snapshot()
            finally:
                self._dispatch_in_flight = False
                self._set_command_input_enabled(True, reason="dispatch_end")
                self._focus_command_input(reason="dispatch_end")
                _emit(runtime, "ui.input.dispatch.completed", command_id=command_id)
            if not should_continue:
                self.exit(0)

        async def on_input_submitted(self, event: Input.Submitted) -> None:
            if self._dispatch_in_flight:
                _emit(runtime, "ui.input.submit.rejected_duplicate", reason="dispatch_in_flight")
                self._set_status("Command already running; wait for completion.")
                return
            raw = str(event.value or "")
            event.input.value = ""
            await self._submit_command(raw=raw, source="input_submitted")

        async def on_key(self, event) -> None:  # noqa: ANN001
            command_input = self.query_one("#command", Input)
            focused_input = self.focused is command_input
            key = str(getattr(event, "key", "") or "")
            character = getattr(event, "character", None)
            is_printable = bool(getattr(event, "is_printable", False))
            consumed, next_value, request_focus, request_submit = _route_key_to_command_input(
                key=key,
                character=character if isinstance(character, str) else None,
                is_printable=is_printable,
                focused_input=focused_input,
                current_value=str(command_input.value or ""),
                dispatch_in_flight=self._dispatch_in_flight,
            )
            if not consumed:
                return
            if request_focus:
                self._focus_command_input(reason="key_reroute")
            if next_value != command_input.value:
                command_input.value = next_value
            _emit(
                runtime,
                "ui.input.key.reroute",
                key=key,
                focused_input=focused_input,
                printable=is_printable,
                submit=request_submit,
            )
            event.stop()
            if request_submit and not self._dispatch_in_flight:
                command_input.value = ""
                await self._submit_command(raw=next_value, source="key_reroute_enter")

        def action_quit(self) -> None:
            self.exit(0)

        def on_unmount(self) -> None:
            _emit(runtime, "ui.screen.exit", screen="dashboard")

    _emit(
        runtime,
        "ui.textual.run_policy",
        screen="dashboard",
        mouse_enabled=run_policy.mouse,
        reason=run_policy.reason,
        term_program=run_policy.term_program,
    )
    return int(DashboardApp().run(mouse=run_policy.mouse) or 0)
