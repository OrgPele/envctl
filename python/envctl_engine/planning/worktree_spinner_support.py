from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from typing import Any

from envctl_engine.ui.spinner_service import SpinnerPolicy, emit_spinner_policy, resolve_spinner_policy


class WorktreeSpinnerLifecycle:
    def __init__(
        self,
        *,
        env: Mapping[str, str],
        emit: Callable[..., None] | None,
        component: str = "worktree_planning",
        emit_when_disabled: bool = False,
        include_stop_enabled: bool = False,
        terminal_fallback: bool = False,
        policy_resolver: Callable[[Mapping[str, str]], SpinnerPolicy] = resolve_spinner_policy,
    ) -> None:
        self._env = env
        self._emit = emit
        self._component = component
        self._emit_when_disabled = emit_when_disabled
        self._include_stop_enabled = include_stop_enabled
        self._terminal_fallback = terminal_fallback
        self._policy_resolver = policy_resolver

    def policy(self, *, op_id: str) -> SpinnerPolicy:
        policy = self._policy_resolver(self._env)
        emit_spinner_policy(
            self._emit,
            policy,
            context={"component": self._component, "op_id": op_id},
        )
        return policy

    def update(
        self,
        *,
        enabled: bool,
        active_spinner: Any,
        op_id: str,
        message: str,
        terminal_message: str | None = None,
    ) -> None:
        rendered = terminal_message or message
        if enabled:
            active_spinner.update(rendered)
        elif self._terminal_fallback:
            print(rendered)
        self._emit_lifecycle(spinner_enabled=enabled, op_id=op_id, state="update", message=message)

    def start(
        self,
        *,
        enabled: bool,
        active_spinner: Any,
        op_id: str,
        message: str,
    ) -> None:
        if enabled:
            active_spinner.start()
        elif self._terminal_fallback:
            print(f"  {message}", file=sys.stderr, flush=True)
        self._emit_lifecycle(spinner_enabled=enabled, op_id=op_id, state="start", message=message)

    def finish(
        self,
        *,
        enabled: bool,
        active_spinner: Any,
        op_id: str,
        message: str,
    ) -> None:
        if enabled:
            active_spinner.succeed(message)
        elif self._terminal_fallback:
            print(f"\u2713 {message}", file=sys.stderr, flush=True)
        self._emit_lifecycle(spinner_enabled=enabled, op_id=op_id, state="success", message=message)

    def fail(
        self,
        *,
        enabled: bool,
        active_spinner: Any,
        op_id: str,
        message: str,
    ) -> None:
        if enabled:
            active_spinner.fail(message)
        elif self._terminal_fallback:
            print(f"\u2717 {message}", file=sys.stderr, flush=True)
        self._emit_lifecycle(spinner_enabled=enabled, op_id=op_id, state="fail", message=message)

    def stop(self, *, enabled: bool, op_id: str) -> None:
        if self._emit is None or (not enabled and not self._emit_when_disabled):
            return
        payload: dict[str, object] = {
            "component": self._component,
            "op_id": op_id,
            "state": "stop",
        }
        if self._include_stop_enabled:
            payload["enabled"] = enabled
        self._emit("ui.spinner.lifecycle", **payload)

    def _emit_lifecycle(
        self,
        *,
        spinner_enabled: bool,
        op_id: str,
        state: str,
        message: str | None = None,
        **extra: object,
    ) -> None:
        if self._emit is None or (not spinner_enabled and not self._emit_when_disabled):
            return
        payload: dict[str, object] = {
            "component": self._component,
            "op_id": op_id,
            "state": state,
        }
        if message is not None:
            payload["message"] = message
        payload.update(extra)
        self._emit("ui.spinner.lifecycle", **payload)


def _runtime_lifecycle(runtime: Any) -> WorktreeSpinnerLifecycle:
    return WorktreeSpinnerLifecycle(
        env=getattr(runtime, "env", {}),
        emit=getattr(runtime, "_emit", None),
        terminal_fallback=True,
    )


def worktree_spinner_policy(runtime: Any, *, op_id: str) -> SpinnerPolicy:
    return _runtime_lifecycle(runtime).policy(op_id=op_id)


def worktree_spinner_update(
    runtime: Any,
    *,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
    terminal_message: str | None = None,
) -> None:
    _runtime_lifecycle(runtime).update(
        enabled=enabled,
        active_spinner=active_spinner,
        op_id=op_id,
        message=message,
        terminal_message=terminal_message,
    )


def worktree_spinner_start(
    runtime: Any,
    *,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
) -> None:
    _runtime_lifecycle(runtime).start(enabled=enabled, active_spinner=active_spinner, op_id=op_id, message=message)


def worktree_spinner_finish(
    runtime: Any,
    *,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
) -> None:
    _runtime_lifecycle(runtime).finish(enabled=enabled, active_spinner=active_spinner, op_id=op_id, message=message)


def worktree_spinner_fail(
    runtime: Any,
    *,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
) -> None:
    _runtime_lifecycle(runtime).fail(enabled=enabled, active_spinner=active_spinner, op_id=op_id, message=message)


def worktree_spinner_stop(runtime: Any, *, enabled: bool, op_id: str) -> None:
    _runtime_lifecycle(runtime).stop(enabled=enabled, op_id=op_id)
