from __future__ import annotations

from contextlib import ExitStack
from typing import Callable

from envctl_engine.ui.prompt_toolkit_list import (
    PromptToolkitListConfig,
    create_prompt_toolkit_tty_io,
    run_prompt_toolkit_list_selector,
)
from envctl_engine.ui.selector_model import SelectorItem

from envctl_engine.ui.textual.screens.selector.support import (
    _emit,
    _emit_selector_debug,
)


def _create_prompt_toolkit_tty_io(*, stack: ExitStack) -> tuple[object, object, str]:
    return create_prompt_toolkit_tty_io(stack=stack)


def _run_prompt_toolkit_selector(
    *,
    prompt: str,
    options: list[SelectorItem],
    multi: bool,
    emit: Callable[..., None] | None,
    deep_debug: bool,
    key_trace_enabled: bool,
    driver_trace_enabled: bool,
    selector_id: str,
) -> list[str] | None:
    if not options:
        return []

    def _row_text(item: SelectorItem) -> str:
        section = str(getattr(item, "section", "") or "").strip()
        kind = str(getattr(item, "kind", "target") or "target").replace("_", " ")
        label = str(getattr(item, "label", "") or "").strip() or str(getattr(item, "token", "target"))
        if section:
            return f"{section} | {label} ({kind})"
        return f"{label} ({kind})"

    result = run_prompt_toolkit_list_selector(
        PromptToolkitListConfig(
            prompt=prompt,
            options=options,
            multi=multi,
            selector_id=selector_id,
            backend_label="prompt_toolkit",
            screen_name="selector_prompt_toolkit",
            focused_widget_id="selector-prompt-toolkit",
            deep_debug=deep_debug,
            driver_trace_enabled=driver_trace_enabled,
            wrap_navigation=False,
            cancel_on_escape=False,
            emit_event=lambda event, **payload: _emit(emit, event, **payload),
            emit_debug=lambda event, **payload: _emit_selector_debug(
                emit,
                enabled=deep_debug,
                event=event,
                **payload,
            ),
            row_text=_row_text,
            confirm_cause="submit_prompt_toolkit",
            cancel_cause="cancel_prompt_toolkit",
            record_raw_keys=key_trace_enabled,
        )
    )

    if result is None:
        _emit(emit, "ui.selection.cancel", prompt=prompt, multi=multi)
        _emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.submit",
            selector_id=selector_id,
            selected_count=0,
            blocked=False,
            cancelled=True,
            cause="cancel_prompt_toolkit_exception",
        )
        return None

    if result.cancelled:
        return None

    if not result.values:
        _emit(
            emit,
            "ui.selection.confirm",
            prompt=prompt,
            multi=multi,
            selected_count=0,
            blocked=True,
        )
        _emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.submit",
            selector_id=selector_id,
            selected_count=0,
            blocked=True,
            cancelled=False,
            cause="submit_prompt_toolkit",
        )
        return []

    _emit(
        emit,
        "ui.selection.confirm",
        prompt=prompt,
        multi=multi,
        selected_count=len(result.values),
    )
    _emit_selector_debug(
        emit,
        enabled=deep_debug,
        event="ui.selector.submit",
        selector_id=selector_id,
        selected_count=len(result.values),
        blocked=False,
        cancelled=False,
        cause="submit_prompt_toolkit",
    )
    return result.values
