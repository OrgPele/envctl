from __future__ import annotations

import time
from collections.abc import Mapping

from ..shared.env_access import float_from_env, int_from_env, str_from_env
from ..shared.parsing import parse_bool


def timeout_error(error: str | None) -> bool:
    normalized = (error or "").lower()
    return "command timed out" in normalized


def sleep_between_probes(process_runner: object, seconds: float) -> None:
    if seconds <= 0:
        return
    sleeper = getattr(process_runner, "sleep", None)
    if callable(sleeper):
        _ = sleeper(seconds)
        return
    time.sleep(seconds)


def env_bool(env: Mapping[str, str] | None, key: str, default: bool) -> bool:
    return parse_bool(str_from_env(env, key), default)


def env_int(env: Mapping[str, str] | None, key: str, default: int, *, minimum: int | None = None) -> int:
    value = int_from_env(env, key, default)
    if minimum is not None:
        return max(minimum, value)
    return value


def env_float(env: Mapping[str, str] | None, key: str, default: float, *, minimum: float | None = None) -> float:
    value = float_from_env(env, key, default)
    if minimum is not None:
        return max(minimum, value)
    return value


def port_mismatch_policy(env: Mapping[str, str] | None) -> str:
    raw = (str_from_env(env, "ENVCTL_REQUIREMENTS_PORT_MISMATCH_POLICY") or "").strip().lower()
    if raw == "recreate":
        return "recreate"
    return "adopt_existing"


def retryable_probe_error(error: str | None, tokens: tuple[str, ...]) -> bool:
    normalized = (error or "").lower()
    return any(token in normalized for token in tokens)


__all__ = tuple(name for name in globals() if not name.startswith("_"))
