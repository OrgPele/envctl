from __future__ import annotations

import os
from typing import Any, Callable, Sequence

from envctl_engine.ui.selector_model import (
    SelectorContext,
    SelectorItem,
    build_grouped_selector_items,
    build_project_selector_items,
)
from envctl_engine.ui.prompt_toolkit_cursor_menu import run_prompt_toolkit_cursor_menu
from envctl_engine.ui.selection_types import TargetSelection
from envctl_engine.ui.terminal_session import can_interactive_tty, prompt_toolkit_available

from envctl_engine.ui.textual.screens.selector.prompt_toolkit_impl import (
    _run_prompt_toolkit_selector as _run_prompt_toolkit_selector_impl,
)
from envctl_engine.ui.textual.screens.selector.textual_impl import (
    run_textual_selector as _run_textual_selector_impl,
)
from envctl_engine.ui.textual.screens.selector.support import (
    _RowRef as _RowRef_impl,
    _deep_debug_enabled as _deep_debug_enabled_impl,
    _emit as _emit_impl,
    _emit_selector_debug as _emit_selector_debug_impl,
    _guard_textual_nonblocking_read as _guard_textual_nonblocking_read_impl,
    _instrument_prompt_toolkit_posix_io as _instrument_prompt_toolkit_posix_io_impl,
    _instrument_textual_parser_keys as _instrument_textual_parser_keys_impl,
    _selector_backend_decision as _selector_backend_decision_impl,
    _selector_disable_focus_reporting_enabled as _selector_disable_focus_reporting_enabled_impl,
    _selector_driver_thread_snapshot as _selector_driver_thread_snapshot_impl,
    _selector_driver_trace_enabled as _selector_driver_trace_enabled_impl,
    _selector_id as _selector_id_impl,
    _selector_impl as _selector_impl_impl,
    _prompt_toolkit_selector_enabled as _prompt_toolkit_selector_enabled_impl,
    _selector_key_trace_enabled as _selector_key_trace_enabled_impl,
    _selector_key_trace_verbose_enabled as _selector_key_trace_verbose_enabled_impl,
    _selector_thread_stack_enabled as _selector_thread_stack_enabled_impl,
    _textual_importable as _textual_importable_impl,
)

_RowRef = _RowRef_impl
_textual_importable = _textual_importable_impl
_emit = _emit_impl
_selector_id = _selector_id_impl
_selector_impl = _selector_impl_impl
_deep_debug_enabled = _deep_debug_enabled_impl
_selector_key_trace_enabled = _selector_key_trace_enabled_impl
_selector_key_trace_verbose_enabled = _selector_key_trace_verbose_enabled_impl
_selector_driver_trace_enabled = _selector_driver_trace_enabled_impl
_selector_thread_stack_enabled = _selector_thread_stack_enabled_impl
_selector_disable_focus_reporting_enabled = _selector_disable_focus_reporting_enabled_impl
_selector_driver_thread_snapshot = _selector_driver_thread_snapshot_impl
_guard_textual_nonblocking_read = _guard_textual_nonblocking_read_impl
_instrument_textual_parser_keys = _instrument_textual_parser_keys_impl
_instrument_prompt_toolkit_posix_io = _instrument_prompt_toolkit_posix_io_impl
_prompt_toolkit_selector_enabled = _prompt_toolkit_selector_enabled_impl
_selector_backend_decision = _selector_backend_decision_impl
_emit_selector_debug = _emit_selector_debug_impl


def _run_prompt_toolkit_selector(**kwargs):
    return _run_prompt_toolkit_selector_impl(**kwargs)

def _run_textual_selector(
    *,
    prompt: str,
    options: list[SelectorItem],
    multi: bool,
    initial_tokens: Sequence[str] | None = None,
    emit: Callable[..., None] | None = None,
    build_only: bool = False,
    force_textual_backend: bool = False,
) -> list[str] | None:
    return _run_textual_selector_impl(
        prompt=prompt,
        options=options,
        multi=multi,
        initial_tokens=initial_tokens,
        emit=emit,
        build_only=build_only,
        force_textual_backend=force_textual_backend,
        selector_backend_decision=_selector_backend_decision,
        run_prompt_toolkit_selector=_run_prompt_toolkit_selector,
    )



def _run_selector_with_impl(
    *,
    prompt: str,
    options: list[SelectorItem],
    multi: bool,
    initial_tokens: Sequence[str] | None = None,
    emit: Callable[..., None] | None = None,
) -> list[str] | None:
    selector_id = _selector_id(prompt)
    deep_debug = _deep_debug_enabled(emit)
    impl = _selector_impl()
    requested_impl_raw = str(os.environ.get("ENVCTL_UI_SELECTOR_IMPL", "")).strip().lower()
    requested_impl = requested_impl_raw or "default"
    effective_engine = (
        "planning_style_prompt_toolkit_rollback"
        if impl == "planning_style"
        else "textual_plan_style"
    )
    rollback_used = impl == "planning_style"
    _emit_selector_debug(
        emit,
        enabled=deep_debug,
        event="ui.selector.engine",
        selector_id=selector_id,
        engine=effective_engine,
        impl=impl,
        requested_impl=requested_impl,
        effective_engine=effective_engine,
        rollback_used=rollback_used,
    )
    if impl != "planning_style":
        return _run_textual_selector(
            prompt=prompt,
            options=options,
            multi=multi,
            initial_tokens=initial_tokens,
            emit=emit,
            force_textual_backend=True,
        )

    use_planning_style = can_interactive_tty() and prompt_toolkit_available()
    if use_planning_style:
        result = run_prompt_toolkit_cursor_menu(
            prompt=prompt,
            options=options,
            multi=multi,
            initial_tokens=initial_tokens,
            emit=emit,
            selector_id=selector_id,
            deep_debug=deep_debug,
        )
        if result is not None:
            return result.values
        _emit(
            emit,
            "ui.fallback.non_interactive",
            reason="planning_style_prompt_toolkit_unavailable",
            command="selector",
        )
    if str(os.environ.get("TERM_PROGRAM", "")).strip() == "Apple_Terminal":
        _emit(
            emit,
            "ui.fallback.non_interactive",
            reason="apple_terminal_selector_requires_prompt_toolkit",
            command="selector",
        )
        return None
    return _run_textual_selector(
        prompt=prompt,
        options=options,
        multi=multi,
        initial_tokens=initial_tokens,
        emit=emit,
        force_textual_backend=True,
    )


def _selection_from_values(values: list[str] | None) -> TargetSelection:
    if values is None:
        return TargetSelection(cancelled=True)
    if not values:
        return TargetSelection(cancelled=True)
    selection = TargetSelection()
    for token in values:
        value = str(token).strip()
        if not value:
            continue
        if value == "__ALL__":
            selection.all_selected = True
            continue
        if value == "__UNTESTED__":
            selection.untested_selected = True
            continue
        if value.startswith("__PROJECT__:"):
            name = value.split(":", 1)[1].strip()
            if name:
                selection.project_names.append(name)
            continue
        selection.service_names.append(value)
    if selection.empty():
        selection.cancelled = True
    return selection


def select_project_targets_textual(
    *,
    prompt: str,
    projects: Sequence[object],
    allow_all: bool,
    allow_untested: bool,
    multi: bool,
    emit: Callable[..., None] | None = None,
    untested_projects: Sequence[str] | None = None,
    initial_project_names: Sequence[str] | None = None,
) -> TargetSelection:
    result = build_project_selector_items(
        SelectorContext(
            projects=projects,
            allow_all=allow_all,
            allow_untested=allow_untested,
            untested_projects=list(untested_projects or []),
            mode="project",
        )
    )
    for suppressed in result.suppressed:
        _emit(
            emit,
            "ui.selection.synthetic_hidden",
            item_id=suppressed.id,
            label=suppressed.label,
            reason=suppressed.reason,
        )
    available_tokens = {
        str(item.label).strip().lower(): str(item.token)
        for item in result.items
        if str(item.kind) == "project"
    }
    initial_tokens: list[str] = []
    for name in initial_project_names or ():
        token = available_tokens.get(str(name).strip().lower())
        if token:
            initial_tokens.append(token)
    values = _run_selector_with_impl(
        prompt=prompt,
        options=result.items,
        multi=multi,
        initial_tokens=initial_tokens,
        emit=emit,
    )
    return _selection_from_values(values)


def select_grouped_targets_textual(
    *,
    prompt: str,
    projects: Sequence[object],
    services: Sequence[str],
    allow_all: bool,
    multi: bool,
    emit: Callable[..., None] | None = None,
) -> TargetSelection:
    result = build_grouped_selector_items(
        SelectorContext(
            projects=projects,
            services=services,
            allow_all=allow_all,
            mode="grouped",
        )
    )
    for suppressed in result.suppressed:
        _emit(
            emit,
            "ui.selection.synthetic_hidden",
            item_id=suppressed.id,
            label=suppressed.label,
            reason=suppressed.reason,
        )
    values = _run_selector_with_impl(prompt=prompt, options=result.items, multi=multi, emit=emit)
    return _selection_from_values(values)
