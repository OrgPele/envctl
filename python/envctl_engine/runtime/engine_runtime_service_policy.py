from __future__ import annotations

import time
from typing import Any

from envctl_engine.shared.parsing import parse_float_or_none, parse_int


def service_rebound_max_delta(runtime: Any) -> int:
    raw = runtime.env.get("ENVCTL_SERVICE_REBOUND_MAX_DELTA") or runtime.config.raw.get(
        "ENVCTL_SERVICE_REBOUND_MAX_DELTA"
    )
    if raw is None:
        return 200
    return max(parse_int(raw, 200), 0)


def service_listener_timeout(runtime: Any) -> float:
    raw = runtime.env.get("ENVCTL_SERVICE_LISTENER_TIMEOUT") or runtime.config.raw.get(
        "ENVCTL_SERVICE_LISTENER_TIMEOUT"
    )
    parsed = parse_float_or_none(raw)
    if isinstance(parsed, float) and parsed > 0:
        return parsed
    return 10.0 if runtime._listener_truth_enforced() else 3.0


def service_truth_timeout(runtime: Any) -> float:
    raw = runtime.env.get("ENVCTL_SERVICE_TRUTH_TIMEOUT") or runtime.config.raw.get("ENVCTL_SERVICE_TRUTH_TIMEOUT")
    parsed = parse_float_or_none(raw)
    if isinstance(parsed, float) and parsed > 0:
        return parsed
    return 0.5


def service_startup_grace_seconds(runtime: Any) -> float:
    raw = runtime.env.get("ENVCTL_SERVICE_STARTUP_GRACE_SECONDS") or runtime.config.raw.get(
        "ENVCTL_SERVICE_STARTUP_GRACE_SECONDS"
    )
    parsed = parse_float_or_none(raw)
    if isinstance(parsed, float) and parsed > 0:
        return parsed
    return 15.0 if runtime._listener_truth_enforced() else 0.0


def service_within_startup_grace(runtime: Any, service: object) -> bool:
    started_at = getattr(service, "started_at", None)
    if not isinstance(started_at, (int, float)):
        return False
    if started_at <= 0:
        return False
    grace_seconds = service_startup_grace_seconds(runtime)
    if grace_seconds <= 0:
        return False
    return (time.time() - float(started_at)) < grace_seconds
