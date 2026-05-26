from __future__ import annotations

from dataclasses import dataclass
import os
import re
import sys
import traceback
from typing import Callable, Mapping

from envctl_engine.ui.capabilities import (
    prompt_toolkit_selector_enabled as _prompt_toolkit_selector_enabled_impl,
    textual_importable as _textual_importable_impl,
)
from envctl_engine.ui.terminal_session import can_interactive_tty, prompt_toolkit_available


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


@dataclass(frozen=True, slots=True)
class SelectorBackendDecision:
    enabled: bool
    info: dict[str, object]


def selector_id(prompt: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(prompt).strip().lower()).strip("_")
    return normalized or "selector"


def selector_impl() -> str:
    simple_menus = _env_value("ENVCTL_UI_SIMPLE_MENUS")
    if simple_menus in TRUE_VALUES:
        return "planning_style"
    if simple_menus in FALSE_VALUES:
        return "textual"
    raw = _env_value("ENVCTL_UI_SELECTOR_IMPL")
    if raw in {"planning_style", "prompt_toolkit", "prompt-toolkit", "ptk"}:
        return "planning_style"
    if raw in {"textual", "textual_plan_style", "legacy"}:
        return "textual"
    return "textual"


def selector_prompt_toolkit_enabled(*, build_only: bool = False) -> bool:
    if build_only:
        return False
    return _prompt_toolkit_selector_enabled_impl(os.environ)


def selector_textual_importable() -> bool:
    return _textual_importable_impl()


def deep_debug_enabled(emit: Callable[..., None] | None) -> bool:
    return _emit_env_value(emit, "ENVCTL_DEBUG_UI_MODE") == "deep"


def selector_key_trace_enabled(emit: Callable[..., None] | None) -> bool:
    if not deep_debug_enabled(emit):
        return False
    value = _emit_env_value(emit, "ENVCTL_DEBUG_SELECTOR_KEYS")
    if value in FALSE_VALUES:
        return False
    # Default in deep mode: collect lightweight key counters and emit one summary.
    return True


def selector_key_trace_verbose_enabled(emit: Callable[..., None] | None) -> bool:
    return _emit_env_value(emit, "ENVCTL_DEBUG_SELECTOR_KEYS_VERBOSE") in TRUE_VALUES


def selector_driver_trace_enabled(emit: Callable[..., None] | None) -> bool:
    deep_debug = deep_debug_enabled(emit)
    value = _emit_env_value(emit, "ENVCTL_DEBUG_SELECTOR_DRIVER_KEYS")
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    # Default in deep mode so incident bundles include parser ingress evidence.
    return deep_debug


def selector_thread_stack_enabled(emit: Callable[..., None] | None) -> bool:
    if not deep_debug_enabled(emit):
        return False
    return _emit_env_value(emit, "ENVCTL_DEBUG_SELECTOR_THREAD_STACK") in TRUE_VALUES


def selector_disable_focus_reporting_enabled(emit: Callable[..., None] | None) -> bool:
    value = _emit_env_value(emit, "ENVCTL_UI_SELECTOR_FOCUS_REPORTING")
    if value in {"1", "true", "yes", "on", "enable", "enabled"}:
        return False
    if value in {"0", "false", "no", "off", "disable", "disabled"}:
        return True
    # Default to disabling focus reports in selector screens to avoid spurious
    # focus-out events swallowing subsequent keyboard interaction on some terminals.
    return True


def selector_driver_thread_snapshot(app: object, *, include_stack: bool) -> dict[str, object]:
    snapshot: dict[str, object] = {}
    try:
        driver = getattr(app, "_driver", None)
    except Exception:
        driver = None
    if driver is None:
        snapshot["driver_present"] = False
        return snapshot
    snapshot["driver_present"] = True
    exit_event = getattr(driver, "exit_event", None)
    is_set = getattr(exit_event, "is_set", None)
    if callable(is_set):
        try:
            snapshot["driver_exit_event_set"] = bool(is_set())
        except Exception:
            snapshot["driver_exit_event_set"] = None
    key_thread = getattr(driver, "_key_thread", None)
    if key_thread is None:
        snapshot["input_thread_present"] = False
        return snapshot
    snapshot["input_thread_present"] = True
    snapshot["input_thread_name"] = str(getattr(key_thread, "name", "") or "")
    snapshot["input_thread_ident"] = getattr(key_thread, "ident", None)
    snapshot["input_thread_native_id"] = getattr(key_thread, "native_id", None)
    snapshot["input_thread_daemon"] = bool(getattr(key_thread, "daemon", False))
    is_alive = getattr(key_thread, "is_alive", None)
    alive = bool(is_alive()) if callable(is_alive) else False
    snapshot["input_thread_alive"] = alive
    if not include_stack or not alive:
        return snapshot
    ident = getattr(key_thread, "ident", None)
    if not isinstance(ident, int):
        snapshot["input_thread_stack"] = []
        return snapshot
    try:
        frame = sys._current_frames().get(ident)
    except Exception:
        frame = None
    if frame is None:
        snapshot["input_thread_stack"] = []
        return snapshot
    try:
        extracted = traceback.extract_stack(frame, limit=8)
        snapshot["input_thread_stack"] = [f"{entry.filename}:{entry.lineno}:{entry.name}" for entry in extracted]
    except Exception as exc:
        snapshot["input_thread_stack_error"] = type(exc).__name__
    return snapshot


def selector_backend_decision(*, build_only: bool) -> tuple[bool, dict[str, object]]:
    decision = build_selector_backend_decision(build_only=build_only)
    return decision.enabled, decision.info


def build_selector_backend_decision(*, build_only: bool) -> SelectorBackendDecision:
    info: dict[str, object] = {"build_only": bool(build_only)}
    can_tty = can_interactive_tty()
    ptk_available = prompt_toolkit_available()
    backend_pref = _env_value("ENVCTL_UI_SELECTOR_BACKEND")
    raw_ptk = _env_value("ENVCTL_UI_PROMPT_TOOLKIT")
    info["can_interactive_tty"] = bool(can_tty)
    info["prompt_toolkit_available"] = bool(ptk_available)
    info["env_selector_backend"] = backend_pref
    info["env_ui_prompt_toolkit"] = raw_ptk

    if build_only:
        return _backend_decision(False, info, reason="build_only", backend="textual")
    if backend_pref in {"textual", "tui"}:
        return _backend_decision(False, info, reason="env_forced_textual", backend="textual")
    if backend_pref in {"prompt_toolkit", "prompt-toolkit", "ptk"}:
        enabled = can_tty and ptk_available
        return _backend_decision(
            bool(enabled),
            info,
            reason="env_forced_prompt_toolkit",
            backend="prompt_toolkit" if enabled else "textual",
        )
    if raw_ptk in TRUE_VALUES:
        enabled = can_tty and ptk_available
        return _backend_decision(
            bool(enabled),
            info,
            reason="env_prompt_toolkit_enabled",
            backend="prompt_toolkit" if enabled else "textual",
        )
    if not can_tty:
        return _backend_decision(False, info, reason="non_tty", backend="textual")
    if raw_ptk in FALSE_VALUES:
        return _backend_decision(False, info, reason="env_prompt_toolkit_disabled", backend="textual")
    if ptk_available:
        return _backend_decision(True, info, reason="default_prompt_toolkit", backend="prompt_toolkit")
    return _backend_decision(False, info, reason="default_textual_prompt_toolkit_missing", backend="textual")


def emit_selector_debug(
    emit: Callable[..., None] | None,
    *,
    enabled: bool,
    event: str,
    **payload: object,
) -> None:
    if not enabled:
        return
    emit_selector_event(emit, event, **payload)


def emit_selector_event(emit: Callable[..., None] | None, event: str, **payload: object) -> None:
    if not callable(emit):
        return
    emit(event, component="ui.textual.selector", **payload)


def _backend_decision(
    enabled: bool,
    info: dict[str, object],
    *,
    reason: str,
    backend: str,
) -> SelectorBackendDecision:
    info["reason"] = reason
    info["backend"] = backend
    return SelectorBackendDecision(enabled=enabled, info=info)


def _emit_env_value(emit: Callable[..., None] | None, key: str) -> str:
    runtime = getattr(emit, "__self__", None)
    env = getattr(runtime, "env", None)
    value = ""
    if isinstance(env, Mapping):
        value = str(env.get(key, "")).strip().lower()
    if not value:
        value = _env_value(key)
    return value


def _env_value(key: str) -> str:
    return str(os.environ.get(key, "")).strip().lower()
