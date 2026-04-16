from __future__ import annotations

import copy
from contextlib import contextmanager
from contextvars import ContextVar
import sys
from typing import Iterator

from .spinner_service import RichSpinnerOperation, SpinnerPolicy, resolve_spinner_policy

Spinner = RichSpinnerOperation
_SPINNER_POLICY_OVERRIDE: ContextVar[SpinnerPolicy | None] = ContextVar(
    "envctl_spinner_policy_override",
    default=None,
)


def spinner_enabled(env: dict[str, str] | None = None) -> bool:
    return resolve_spinner_policy(env).enabled


@contextmanager
def use_spinner_policy(policy: SpinnerPolicy | None) -> Iterator[None]:
    token = _SPINNER_POLICY_OVERRIDE.set(policy)
    try:
        yield
    finally:
        _SPINNER_POLICY_OVERRIDE.reset(token)


@contextmanager
def spinner(message: str, *, enabled: bool, start_immediately: bool = True) -> Iterator[Spinner]:
    resolved = _SPINNER_POLICY_OVERRIDE.get()
    if resolved is None:
        policy = resolve_spinner_policy({})
    else:
        policy = copy.copy(resolved)
    policy.enabled = bool(enabled) and policy.enabled
    if not policy.enabled and not policy.reason:
        policy.reason = "env_off"
    s = Spinner(
        message=message,
        policy=policy,
        start_immediately=start_immediately,
    )
    if not policy.enabled:
        try:
            write = getattr(sys.stderr, "write", None)
            if callable(write):
                write(f"  {message}\n")
                flush = getattr(sys.stderr, "flush", None)
                if callable(flush):
                    flush()
        except Exception:
            pass
    try:
        yield s
    finally:
        s.end()
