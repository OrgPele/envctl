from __future__ import annotations

from dataclasses import dataclass

from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.terminal_session import can_interactive_tty, prompt_toolkit_available

from . import backend_policy as _backend_policy
from .backend_policy import (
    deep_debug_enabled as _deep_debug_enabled,
    emit_selector_debug as _emit_selector_debug,
    emit_selector_event as _emit,
    selector_disable_focus_reporting_enabled as _selector_disable_focus_reporting_enabled,
    selector_driver_thread_snapshot as _selector_driver_thread_snapshot,
    selector_driver_trace_enabled as _selector_driver_trace_enabled,
    selector_id as _selector_id,
    selector_impl as _selector_impl,
    selector_key_trace_enabled as _selector_key_trace_enabled,
    selector_key_trace_verbose_enabled as _selector_key_trace_verbose_enabled,
    selector_prompt_toolkit_enabled as _prompt_toolkit_selector_enabled,
    selector_textual_importable as _textual_importable,
    selector_thread_stack_enabled as _selector_thread_stack_enabled,
)
from .io_probe import SelectorIoProbe
from .prompt_toolkit_io_instrumentation import (
    instrument_prompt_toolkit_posix_io as _instrument_prompt_toolkit_posix_io,
)
from .read_guard import guard_textual_nonblocking_read as _guard_textual_nonblocking_read
from .textual_driver_instrumentation import instrument_textual_parser_keys as _instrument_textual_parser_keys

__all__ = [
    "SelectorIoProbe",
    "_RowRef",
    "_deep_debug_enabled",
    "_emit",
    "_emit_selector_debug",
    "_guard_textual_nonblocking_read",
    "_instrument_prompt_toolkit_posix_io",
    "_instrument_textual_parser_keys",
    "_prompt_toolkit_selector_enabled",
    "_selector_backend_decision",
    "_selector_disable_focus_reporting_enabled",
    "_selector_driver_thread_snapshot",
    "_selector_driver_trace_enabled",
    "_selector_id",
    "_selector_impl",
    "_selector_key_trace_enabled",
    "_selector_key_trace_verbose_enabled",
    "_selector_thread_stack_enabled",
    "_textual_importable",
]


@dataclass(slots=True)
class _RowRef:
    item: SelectorItem
    selected: bool = False
    visible: bool = True


def _selector_backend_decision(*, build_only: bool) -> tuple[bool, dict[str, object]]:
    _backend_policy.can_interactive_tty = can_interactive_tty
    _backend_policy.prompt_toolkit_available = prompt_toolkit_available
    return _backend_policy.selector_backend_decision(build_only=build_only)
