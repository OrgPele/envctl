from __future__ import annotations

from contextlib import nullcontext
import os
import select
import sys
from typing import Callable, Sequence, cast

from envctl_engine.ui.textual.screens.selector.support import (
    _deep_debug_enabled,
    _emit,
    _emit_selector_debug,
    _guard_textual_nonblocking_read,
    _instrument_textual_parser_keys,
    _selector_backend_decision,
    _selector_disable_focus_reporting_enabled,
    _selector_driver_trace_enabled,
    _selector_id,
    _selector_key_trace_enabled,
    _selector_key_trace_verbose_enabled,
    _selector_thread_stack_enabled,
    _textual_importable,
)
from envctl_engine.ui.textual.compat import textual_run_policy
from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.terminal_session import consume_preserved_input, temporary_tty_character_mode
from envctl_engine.ui.textual.screens.selector.prompt_toolkit_impl import (
    _run_prompt_toolkit_selector,
)
from envctl_engine.ui.textual.screens.selector.textual_app import (
    create_selector_app,
)


def _drain_pending_selector_input(*, tty_fd: int | None, max_bytes: int = 64) -> bytes:
    if tty_fd is None or max_bytes <= 0:
        return b""
    collected = bytearray()
    while len(collected) < max_bytes:
        try:
            ready, _, _ = select.select([tty_fd], [], [], 0)
        except Exception:
            break
        if not ready:
            break
        try:
            chunk = os.read(tty_fd, 1)
        except Exception:
            break
        if not chunk:
            break
        collected.extend(chunk)
    return bytes(collected)


def _consume_initial_selector_actions(*, tty_fd: int | None) -> tuple[str, ...]:
    raw = consume_preserved_input() + _drain_pending_selector_input(tty_fd=tty_fd)
    if not raw:
        return ()
    actions: list[str] = []
    index = 0
    while index < len(raw):
        if raw[index : index + 3] == b"\x1b[A":
            actions.append("up")
            index += 3
            continue
        if raw[index : index + 3] == b"\x1b[B":
            actions.append("down")
            index += 3
            continue
        if raw[index : index + 2] in {b"\r\n", b"\n\r"}:
            actions.append("submit")
            index += 2
            continue
        if raw[index : index + 1] in {b"\r", b"\n"}:
            actions.append("submit")
            index += 1
            continue
        index += 1
    return tuple(actions)


def run_textual_selector(
    *,
    prompt: str,
    options: list[SelectorItem],
    multi: bool,
    initial_tokens: Sequence[str] | None = None,
    emit: Callable[..., None] | None = None,
    exclusive_token: str | None = None,
    build_only: bool = False,
    force_textual_backend: bool = False,
    selector_backend_decision: Callable[..., tuple[bool, dict[str, object]]] | None = None,
    run_prompt_toolkit_selector: Callable[..., list[str] | None] | None = None,
) -> list[str] | None:
    if not options:
        return []
    if not _textual_importable():
        _emit(emit, "ui.fallback.non_interactive", reason="textual_missing", command="selector")
        return None
    tty_fd: int | None = None
    if not build_only:
        try:
            fd = int(sys.stdin.fileno())
            if os.isatty(fd):
                tty_fd = fd
        except Exception:
            tty_fd = None
    # Keep ESC parsing responsive by default; allow explicit override.
    # Large ESCDELAY values can make arrow navigation feel sluggish.
    esc_delay_default_raw = str(os.environ.get("ENVCTL_UI_SELECTOR_ESCDELAY", "")).strip()
    try:
        esc_delay_default = int(esc_delay_default_raw) if esc_delay_default_raw else 300
    except ValueError:
        esc_delay_default = 300
    esc_delay_default = max(25, min(500, esc_delay_default))
    esc_delay_raw = str(os.environ.get("ESCDELAY", "")).strip()
    try:
        esc_delay_ms = int(esc_delay_raw) if esc_delay_raw else 0
    except ValueError:
        esc_delay_ms = 0
    esc_delay_effective_ms = esc_delay_ms if esc_delay_ms > 0 else esc_delay_default
    if esc_delay_ms <= 0:
        os.environ["ESCDELAY"] = str(esc_delay_default)

    selector_id = _selector_id(prompt)
    initial_token_set = {str(token).strip() for token in (initial_tokens or []) if str(token).strip()}
    deep_debug = _deep_debug_enabled(emit)
    key_trace_enabled = _selector_key_trace_enabled(emit)
    key_trace_verbose = _selector_key_trace_verbose_enabled(emit)
    driver_trace_enabled = _selector_driver_trace_enabled(emit)
    thread_stack_enabled = _selector_thread_stack_enabled(emit)
    disable_focus_reporting = _selector_disable_focus_reporting_enabled(emit)
    driver_probe: Callable[[], dict[str, object]] | None = None
    if selector_backend_decision is None:
        selector_backend_decision = _selector_backend_decision
    if run_prompt_toolkit_selector is None:
        run_prompt_toolkit_selector = _run_prompt_toolkit_selector
    if force_textual_backend:
        use_prompt_toolkit = False
        backend_info: dict[str, object] = {
            "build_only": bool(build_only),
            "backend": "textual",
            "reason": "forced_textual_backend",
            "forced_textual_backend": True,
        }
    else:
        use_prompt_toolkit, backend_info = selector_backend_decision(build_only=build_only)
    _emit_selector_debug(
        emit,
        enabled=deep_debug,
        event="ui.selector.backend",
        selector_id=selector_id,
        **backend_info,
    )
    if use_prompt_toolkit:
        result = run_prompt_toolkit_selector(
            prompt=prompt,
            options=options,
            multi=multi,
            exclusive_token=exclusive_token,
            emit=emit,
            deep_debug=deep_debug,
            key_trace_enabled=key_trace_enabled,
            driver_trace_enabled=driver_trace_enabled,
            selector_id=selector_id,
        )
        if result is not None or not build_only:
            return result

    if build_only:
        run_policy = textual_run_policy(screen="selector")
        initial_navigation = _consume_initial_selector_actions(tty_fd=tty_fd)
        app = create_selector_app(
            prompt=prompt,
            options=options,
            multi=multi,
            initial_token_set=initial_token_set,
            emit=emit,
            deep_debug=deep_debug,
            key_trace_enabled=key_trace_enabled,
            key_trace_verbose=key_trace_verbose,
            driver_trace_enabled=driver_trace_enabled,
            driver_probe=None,
            thread_stack_enabled=thread_stack_enabled,
            disable_focus_reporting=disable_focus_reporting,
            mouse_enabled=run_policy.mouse,
            selector_id=selector_id,
            initial_navigation=initial_navigation,
            exclusive_token=exclusive_token,
        )
        return app  # type: ignore[return-value]
    prelaunch_mode = (
        temporary_tty_character_mode(fd=tty_fd, emit=emit)
        if tty_fd is not None and force_textual_backend
        else nullcontext(False)
    )
    with prelaunch_mode:
        launch_mode = (
            nullcontext(False)
            if tty_fd is not None and force_textual_backend
            else temporary_tty_character_mode(fd=tty_fd, emit=emit)
            if tty_fd is not None
            else nullcontext(False)
        )
        with launch_mode:
            with _guard_textual_nonblocking_read(
                emit=emit,
                selector_id=selector_id,
                deep_debug=deep_debug,
            ):
                with _instrument_textual_parser_keys(
                    emit=emit,
                    enabled=driver_trace_enabled,
                    selector_id=selector_id,
                    deep_debug=deep_debug,
                    esc_delay_env_ms=esc_delay_effective_ms,
                ) as _driver_probe:
                    driver_probe = cast(Callable[[], dict[str, object]] | None, _driver_probe)
                    run_policy = textual_run_policy(screen="selector")
                    initial_navigation = _consume_initial_selector_actions(tty_fd=tty_fd)
                    app = create_selector_app(
                        prompt=prompt,
                        options=options,
                        multi=multi,
                        initial_token_set=initial_token_set,
                        emit=emit,
                        deep_debug=deep_debug,
                        key_trace_enabled=key_trace_enabled,
                        key_trace_verbose=key_trace_verbose,
                        driver_trace_enabled=driver_trace_enabled,
                        driver_probe=driver_probe,
                        thread_stack_enabled=thread_stack_enabled,
                        disable_focus_reporting=disable_focus_reporting,
                        mouse_enabled=run_policy.mouse,
                        selector_id=selector_id,
                        initial_navigation=initial_navigation,
                        exclusive_token=exclusive_token,
                    )
                    try:
                        import textual.constants as textual_constants  # type: ignore

                        before_ms = int(float(textual_constants.ESCAPE_DELAY) * 1000.0)
                        textual_constants.ESCAPE_DELAY = float(esc_delay_effective_ms) / 1000.0
                        _emit_selector_debug(
                            emit,
                            enabled=deep_debug,
                            event="ui.selector.key.driver.escape_delay",
                            selector_id=selector_id,
                            before_ms=before_ms,
                            applied_ms=esc_delay_effective_ms,
                            source=("env" if esc_delay_ms > 0 else "default"),
                        )
                    except Exception as exc:
                        _emit_selector_debug(
                            emit,
                            enabled=deep_debug,
                            event="ui.selector.key.driver.escape_delay",
                            selector_id=selector_id,
                            before_ms=None,
                            applied_ms=esc_delay_effective_ms,
                            source=("env" if esc_delay_ms > 0 else "default"),
                            error=type(exc).__name__,
                        )
                    _emit_selector_debug(
                        emit,
                        enabled=deep_debug,
                        event="ui.textual.run_policy",
                        selector_id=selector_id,
                        screen="selector",
                        mouse_enabled=run_policy.mouse,
                        reason=run_policy.reason,
                        term_program=run_policy.term_program,
                    )
                result = app.run(mouse=run_policy.mouse)
    if result is None and not app.explicit_cancel:
        recovered = app.fallback_values()
        if recovered:
            _emit_selector_debug(
                emit,
                enabled=deep_debug,
                event="ui.selector.submit",
                selector_id=selector_id,
                selected_count=len(recovered),
                blocked=False,
                cancelled=False,
                cause="implicit_recovery",
            )
            return recovered
    return result
