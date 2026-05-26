from __future__ import annotations

import os
import sys
import threading
import traceback
from typing import Any, Mapping


def debug_orch_groups(runtime: Any) -> set[str]:
    raw = ""
    env = getattr(runtime, "env", None)
    if isinstance(env, Mapping):
        raw = str(env.get("ENVCTL_DEBUG_PLAN_ORCH_GROUP", "")).strip().lower()
    if not raw:
        raw = str(os.environ.get("ENVCTL_DEBUG_PLAN_ORCH_GROUP", "")).strip().lower()
    return {token.strip() for token in raw.replace("+", ",").split(",") if token.strip()}


def debug_tty_groups(runtime: Any) -> set[str]:
    orch_groups = debug_orch_groups(runtime)
    if orch_groups and "tty" not in orch_groups:
        return set()
    raw = ""
    env = getattr(runtime, "env", None)
    if isinstance(env, Mapping):
        raw = str(env.get("ENVCTL_DEBUG_PLAN_TTY_GROUP", "")).strip().lower()
    if not raw:
        raw = str(os.environ.get("ENVCTL_DEBUG_PLAN_TTY_GROUP", "")).strip().lower()
    return {token.strip() for token in raw.replace("+", ",").split(",") if token.strip()}


def debug_tty_group_enabled(runtime: Any, name: str) -> bool:
    groups = debug_tty_groups(runtime)
    if not groups:
        return True
    return name in groups


def emit_debug_tty_group(runtime: Any, *, group: str, action: str, enabled: bool, detail: str) -> None:
    emit = getattr(runtime, "_emit", None)
    if not callable(emit):
        return
    emit(
        "startup.debug_tty_group",
        component="ui.backend",
        group=group,
        action=action,
        enabled=enabled,
        detail=detail,
    )


def emit_parent_selector_thread_snapshot(*, emit: Any, stage: str) -> None:
    if not callable(emit):
        return
    try:
        current_frames = sys._current_frames()
    except Exception:
        current_frames = {}
    threads: list[dict[str, object]] = []
    for thread in threading.enumerate():
        frame = current_frames.get(thread.ident) if thread.ident is not None else None
        stack: list[str] = []
        if frame is not None:
            try:
                stack = [f"{item.filename}:{item.lineno}:{item.name}" for item in traceback.extract_stack(frame)[-12:]]
            except Exception:
                stack = []
        threads.append(
            {
                "name": thread.name,
                "ident": thread.ident,
                "daemon": thread.daemon,
                "alive": thread.is_alive(),
                "stack": stack,
            }
        )
    emit(
        "ui.selector.subprocess.parent_threads",
        component="ui.backend",
        stage=stage,
        thread_count=len(threads),
        threads=threads,
    )


_debug_orch_groups = debug_orch_groups
_debug_tty_groups = debug_tty_groups
_debug_tty_group_enabled = debug_tty_group_enabled
_emit_debug_tty_group = emit_debug_tty_group
_emit_parent_selector_thread_snapshot = emit_parent_selector_thread_snapshot
