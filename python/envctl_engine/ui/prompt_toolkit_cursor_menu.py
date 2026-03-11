from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from typing import Callable, Sequence

from envctl_engine.ui.prompt_toolkit_list import (
    PromptToolkitListConfig,
    PromptToolkitListResult,
    create_prompt_toolkit_tty_io,
    run_prompt_toolkit_list_selector,
)

from .selector_model import SelectorItem


@dataclass(slots=True)
class CursorMenuResult:
    values: list[str] | None
    cancelled: bool


def _emit(emit: Callable[..., None] | None, event: str, **payload: object) -> None:
    if callable(emit):
        emit(event, component="ui.prompt_toolkit_cursor_menu", **payload)


def _create_prompt_toolkit_tty_io(*, stack: ExitStack) -> tuple[object, object, str]:
    return create_prompt_toolkit_tty_io(stack=stack)


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
    def _emit_debug(event: str, **payload: object) -> None:
        if deep_debug:
            _emit(emit, event, **payload)

    result = run_prompt_toolkit_list_selector(
        PromptToolkitListConfig(
            prompt=prompt,
            options=options,
            multi=multi,
            initial_tokens=initial_tokens,
            selector_id=selector_id,
            backend_label="planning_style_prompt_toolkit",
            screen_name="selector_prompt_toolkit_cursor",
            focused_widget_id="selector-prompt-toolkit-cursor",
            deep_debug=deep_debug,
            driver_trace_enabled=deep_debug,
            wrap_navigation=True,
            cancel_on_escape=True,
            emit_event=lambda event, **payload: _emit(emit, event, **payload),
            emit_debug=_emit_debug,
            help_text_multi="UP/DOWN or j/k/w/s move  Space/x toggle  a/Ctrl+A all  Enter submit  q/Esc/Ctrl+C cancel",
            help_text_single="UP/DOWN or j/k/w/s move  Space/x select  Enter submit  q/Esc/Ctrl+C cancel",
            confirm_cause="enter",
            cancel_cause="cancel_key",
            record_raw_keys=True,
        )
    )
    if isinstance(result, PromptToolkitListResult):
        return CursorMenuResult(values=result.values, cancelled=result.cancelled)
    return None
