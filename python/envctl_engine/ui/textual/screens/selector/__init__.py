"""Selector screen package.

This package keeps a compatibility facade so tests and older callers can patch
`envctl_engine.ui.textual.screens.selector.*` directly even though the
implementation now lives in a submodule.
"""

from __future__ import annotations

from typing import Any

from . import implementation as _impl
from . import support as _support

_ORIG_RUN_PROMPT_TOOLKIT_SELECTOR = _impl._run_prompt_toolkit_selector
_ORIG_RUN_TEXTUAL_SELECTOR = _impl._run_textual_selector
_ORIG_RUN_SELECTOR_WITH_IMPL = _impl._run_selector_with_impl
_ORIG_SELECT_PROJECT_TARGETS_TEXTUAL = _impl.select_project_targets_textual
_ORIG_SELECT_GROUPED_TARGETS_TEXTUAL = _impl.select_grouped_targets_textual
_ORIG_SELECTOR_BACKEND_DECISION = _impl._selector_backend_decision

SelectorItem = _impl.SelectorItem
can_interactive_tty = _impl.can_interactive_tty
prompt_toolkit_available = _impl.prompt_toolkit_available
_RowRef = _impl._RowRef
_textual_importable = _impl._textual_importable
_emit = _impl._emit
_selector_id = _impl._selector_id
_selector_impl = _impl._selector_impl
_deep_debug_enabled = _impl._deep_debug_enabled
_selector_key_trace_enabled = _impl._selector_key_trace_enabled
_selector_key_trace_verbose_enabled = _impl._selector_key_trace_verbose_enabled
_selector_driver_trace_enabled = _impl._selector_driver_trace_enabled
_selector_thread_stack_enabled = _impl._selector_thread_stack_enabled
_selector_disable_focus_reporting_enabled = _impl._selector_disable_focus_reporting_enabled
_selector_driver_thread_snapshot = _impl._selector_driver_thread_snapshot
_guard_textual_nonblocking_read = _impl._guard_textual_nonblocking_read
_instrument_textual_parser_keys = _impl._instrument_textual_parser_keys
_instrument_prompt_toolkit_posix_io = _impl._instrument_prompt_toolkit_posix_io
run_prompt_toolkit_cursor_menu = _impl.run_prompt_toolkit_cursor_menu
_emit_selector_debug = _impl._emit_selector_debug
_selection_from_values = _impl._selection_from_values


def _sync_impl_aliases() -> None:
    _impl.SelectorItem = SelectorItem
    _impl.can_interactive_tty = can_interactive_tty
    _impl.prompt_toolkit_available = prompt_toolkit_available
    _impl._RowRef = _RowRef
    _impl._textual_importable = _textual_importable
    _impl._emit = _emit
    _impl._selector_id = _selector_id
    _impl._selector_impl = _selector_impl
    _impl._deep_debug_enabled = _deep_debug_enabled
    _impl._selector_key_trace_enabled = _selector_key_trace_enabled
    _impl._selector_key_trace_verbose_enabled = _selector_key_trace_verbose_enabled
    _impl._selector_driver_trace_enabled = _selector_driver_trace_enabled
    _impl._selector_thread_stack_enabled = _selector_thread_stack_enabled
    _impl._selector_disable_focus_reporting_enabled = _selector_disable_focus_reporting_enabled
    _impl._selector_driver_thread_snapshot = _selector_driver_thread_snapshot
    _impl._guard_textual_nonblocking_read = _guard_textual_nonblocking_read
    _impl._instrument_textual_parser_keys = _instrument_textual_parser_keys
    _impl._instrument_prompt_toolkit_posix_io = _instrument_prompt_toolkit_posix_io
    _impl.run_prompt_toolkit_cursor_menu = run_prompt_toolkit_cursor_menu
    _impl._emit_selector_debug = _emit_selector_debug
    _impl._selection_from_values = _selection_from_values
    _impl._run_prompt_toolkit_selector = _run_prompt_toolkit_selector
    _impl._run_textual_selector = _run_textual_selector
    _impl._run_selector_with_impl = _run_selector_with_impl
    _impl.select_project_targets_textual = select_project_targets_textual
    _impl.select_grouped_targets_textual = select_grouped_targets_textual
    _support.can_interactive_tty = can_interactive_tty
    _support.prompt_toolkit_available = prompt_toolkit_available


def _run_prompt_toolkit_selector(**kwargs: Any):
    _sync_impl_aliases()
    return _ORIG_RUN_PROMPT_TOOLKIT_SELECTOR(**kwargs)


def _run_textual_selector(**kwargs: Any):
    _sync_impl_aliases()
    return _ORIG_RUN_TEXTUAL_SELECTOR(**kwargs)


def _run_selector_with_impl(**kwargs: Any):
    _sync_impl_aliases()
    return _ORIG_RUN_SELECTOR_WITH_IMPL(**kwargs)


def _selector_backend_decision(*, build_only: bool):
    _sync_impl_aliases()
    return _ORIG_SELECTOR_BACKEND_DECISION(build_only=build_only)


def _prompt_toolkit_selector_enabled(*, build_only: bool) -> bool:
    enabled, _info = _selector_backend_decision(build_only=build_only)
    return bool(enabled)


def select_project_targets_textual(**kwargs: Any):
    _sync_impl_aliases()
    return _ORIG_SELECT_PROJECT_TARGETS_TEXTUAL(**kwargs)


def select_grouped_targets_textual(**kwargs: Any):
    _sync_impl_aliases()
    return _ORIG_SELECT_GROUPED_TARGETS_TEXTUAL(**kwargs)


_sync_impl_aliases()


__all__ = [
    "SelectorItem",
    "can_interactive_tty",
    "prompt_toolkit_available",
    "_RowRef",
    "_textual_importable",
    "_emit",
    "_selector_id",
    "_selector_impl",
    "_deep_debug_enabled",
    "_selector_key_trace_enabled",
    "_selector_key_trace_verbose_enabled",
    "_selector_driver_trace_enabled",
    "_selector_thread_stack_enabled",
    "_selector_disable_focus_reporting_enabled",
    "_selector_driver_thread_snapshot",
    "_guard_textual_nonblocking_read",
    "_instrument_textual_parser_keys",
    "_instrument_prompt_toolkit_posix_io",
    "run_prompt_toolkit_cursor_menu",
    "_prompt_toolkit_selector_enabled",
    "_selector_backend_decision",
    "_emit_selector_debug",
    "_selection_from_values",
    "_run_prompt_toolkit_selector",
    "_run_textual_selector",
    "_run_selector_with_impl",
    "select_project_targets_textual",
    "select_grouped_targets_textual",
]
