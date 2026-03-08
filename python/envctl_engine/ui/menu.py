from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import importlib
import os
from typing import Any, Protocol, cast

from .terminal_session import TerminalSession, can_interactive_tty, prompt_toolkit_available


@dataclass(frozen=True)
class MenuOption:
    label: str
    value: str


class MenuPresenter(Protocol):
    def select_single(self, prompt: str, options: list[MenuOption]) -> str | None: ...

    def select_multi(self, prompt: str, options: list[MenuOption]) -> list[str] | None: ...


class PromptToolkitMenuPresenter:
    @staticmethod
    def _dialog_style() -> object:
        styles = importlib.import_module("prompt_toolkit.styles")
        style_from_dict = cast(Any, getattr(styles, "Style")).from_dict
        return style_from_dict(
            {
                "dialog": "bg:#10131a #e6edf3",
                "dialog frame.label": "bg:#1f6feb #ffffff bold",
                "dialog.body": "bg:#10131a #e6edf3",
                "dialog shadow": "bg:#000000",
                "button": "bg:#30363d #e6edf3",
                "button.focused": "bg:#1f6feb #ffffff bold",
                "checkbox": "#8b949e",
                "checkbox-selected": "#2ea043 bold",
                "radio": "#8b949e",
                "radio-selected": "#58a6ff bold",
            }
        )

    def select_single(self, prompt: str, options: list[MenuOption]) -> str | None:
        shortcuts = importlib.import_module("prompt_toolkit.shortcuts")
        radiolist_dialog = cast(Any, getattr(shortcuts, "radiolist_dialog"))

        values = [(opt.value, opt.label) for opt in options]
        try:
            return radiolist_dialog(title=prompt, text=prompt, values=values, style=self._dialog_style()).run()
        except (EOFError, KeyboardInterrupt):
            return None

    def select_multi(self, prompt: str, options: list[MenuOption]) -> list[str] | None:
        shortcuts = importlib.import_module("prompt_toolkit.shortcuts")
        checkboxlist_dialog = cast(Any, getattr(shortcuts, "checkboxlist_dialog"))

        values = [(opt.value, opt.label) for opt in options]
        try:
            return checkboxlist_dialog(title=prompt, text=prompt, values=values, style=self._dialog_style()).run()
        except (EOFError, KeyboardInterrupt):
            return None


class FallbackMenuPresenter:
    def __init__(self, *, input_provider: Callable[[str], str], emit: Callable[..., None] | None = None) -> None:
        self._input_provider = input_provider
        self._emit = emit

    def select_single(self, prompt: str, options: list[MenuOption]) -> str | None:
        selection = self._select_values(prompt, options, multi=False)
        if not selection:
            return None
        return selection[0]

    def select_multi(self, prompt: str, options: list[MenuOption]) -> list[str] | None:
        return self._select_values(prompt, options, multi=True)

    def _select_values(self, prompt: str, options: list[MenuOption], *, multi: bool) -> list[str] | None:
        if not options:
            return None
        for idx, option in enumerate(options, start=1):
            print(f"[{idx}] {option.label}")
        suffix = "comma-separated" if multi else "number"
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            self._emit_event(
                "ui.menu.read.begin",
                prompt=prompt,
                multi=multi,
                option_count=len(options),
                attempt=attempt,
            )
            raw = self._input_provider(f"{prompt} ({suffix}, or q to cancel): ")
            length = len(raw) if isinstance(raw, str) else 0
            self._emit_event(
                "ui.menu.read.end",
                prompt=prompt,
                multi=multi,
                bytes_read=length,
                attempt=attempt,
            )
            if raw is None:
                return None
            text = str(raw).strip().lower()
            if text == "q":
                self._emit_event("ui.menu.read.cancel", prompt=prompt, reason="explicit_q", attempt=attempt)
                return None
            if not text:
                self._emit_event("ui.menu.read.retry", prompt=prompt, reason="empty", attempt=attempt)
                if attempt < max_attempts:
                    print("Select at least one option, or q to cancel.")
                    continue
                return None
            parts = [part.strip() for part in text.split(",") if part.strip()]
            if not parts:
                self._emit_event("ui.menu.read.retry", prompt=prompt, reason="empty_tokens", attempt=attempt)
                if attempt < max_attempts:
                    print("Select at least one option, or q to cancel.")
                    continue
                return None
            selections: list[str] = []
            invalid_tokens = 0
            for part in parts:
                if not part.isdigit():
                    invalid_tokens += 1
                    continue
                idx = int(part)
                if idx < 1 or idx > len(options):
                    invalid_tokens += 1
                    continue
                selections.append(options[idx - 1].value)
                if not multi:
                    break
            if selections:
                if invalid_tokens > 0:
                    self._emit_event(
                        "ui.menu.read.partial_invalid",
                        prompt=prompt,
                        invalid_tokens=invalid_tokens,
                        attempt=attempt,
                    )
                return selections
            self._emit_event(
                "ui.menu.read.retry",
                prompt=prompt,
                reason="invalid_selection",
                attempt=attempt,
                invalid_tokens=invalid_tokens,
            )
            if attempt < max_attempts:
                print("Invalid selection. Enter option number(s), or q to cancel.")
                continue
            return None
        return None

    def _emit_event(self, event: str, **payload: object) -> None:
        if self._emit is None:
            return
        try:
            self._emit(event, component="ui.menu.fallback", **payload)
        except Exception:
            return


def _prompt_toolkit_disabled(env: Mapping[str, str]) -> bool:
    raw = env.get("ENVCTL_UI_PROMPT_TOOLKIT")
    if raw is None:
        raw = os.environ.get("ENVCTL_UI_PROMPT_TOOLKIT")
    if raw is None:
        return False
    return str(raw).strip().lower() in {"0", "false", "no", "off"}


def build_menu_presenter(
    env: Mapping[str, str],
    *,
    input_provider: Callable[[str], str] | None = None,
    emit: Callable[..., None] | None = None,
) -> MenuPresenter:
    interactive_tty = can_interactive_tty()
    if input_provider is not None:
        provider = input_provider
    elif interactive_tty:
        provider = TerminalSession(env, emit=emit).read_command_line
    else:
        provider = input
    presenter: MenuPresenter
    backend = "fallback"
    if interactive_tty:
        if not _prompt_toolkit_disabled(env) and prompt_toolkit_available():
            presenter = PromptToolkitMenuPresenter()
            backend = "prompt_toolkit"
        else:
            presenter = FallbackMenuPresenter(input_provider=provider, emit=emit)
    else:
        presenter = FallbackMenuPresenter(input_provider=provider, emit=emit)
    _emit_menu_backend(emit, backend)
    return presenter


def _emit_menu_backend(emit: Callable[..., None] | None, backend: str) -> None:
    if emit is None:
        return
    try:
        emit("ui.menu.backend", backend=backend)
    except Exception:
        return
