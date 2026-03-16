from __future__ import annotations

import time
from typing import Any, Callable

from envctl_engine.ui.textual.compat import apply_textual_driver_compat
from envctl_engine.ui.textual.screens.selector.support import (
    _emit,
    _emit_selector_debug,
)


async def apply_selector_mount(
    app: Any,
    *,
    emit: Callable[..., None] | None,
    deep_debug: bool,
    disable_focus_reporting: bool,
    key_trace_enabled: bool,
    selector_id: str,
    prompt: str,
    option_count: int,
    multi: bool,
    Input: Any,
    mouse_enabled: bool,
) -> None:
    _emit(
        emit,
        "ui.screen.enter",
        screen="selector",
        prompt=prompt,
        option_count=option_count,
        multi=multi,
    )
    _emit_selector_debug(
        emit,
        enabled=deep_debug,
        event="ui.selector.lifecycle",
        selector_id=selector_id,
        prompt=prompt,
        option_count=option_count,
        multi=multi,
        phase="enter",
        ts_mono_ns=time.monotonic_ns(),
    )
    await app._render_rows()
    app.action_focus_list(reason="mount")
    app.call_after_refresh(lambda: app.action_focus_list(reason="mount_after_refresh"))
    if disable_focus_reporting or not mouse_enabled:
        try:
            driver = getattr(app.app, "_driver", None)
            apply_textual_driver_compat(
                driver=driver,
                screen="selector",
                mouse_enabled=mouse_enabled,
                disable_focus_reporting=disable_focus_reporting,
                emit=emit,
                selector_id=selector_id,
            )
            if disable_focus_reporting:
                _emit_selector_debug(
                    emit,
                    enabled=deep_debug,
                    event="ui.selector.key.driver.focus_reporting",
                    selector_id=selector_id,
                    disabled=True,
                )
        except Exception as exc:
            _emit_selector_debug(
                emit,
                enabled=deep_debug,
                event="ui.selector.key.driver.focus_reporting",
                selector_id=selector_id,
                disabled=False,
                error=type(exc).__name__,
            )
    if key_trace_enabled:
        app._key_snapshot_timer = app.set_interval(0.75, app._emit_key_snapshot)
