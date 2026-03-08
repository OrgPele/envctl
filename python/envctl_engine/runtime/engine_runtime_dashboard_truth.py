from __future__ import annotations

import time
from typing import Any

from envctl_engine.shared.parsing import parse_float_or_none


def dashboard_truth_refresh_seconds(runtime: Any) -> float:
    raw = runtime.env.get("ENVCTL_DASHBOARD_TRUTH_REFRESH_SECONDS") or runtime.config.raw.get(
        "ENVCTL_DASHBOARD_TRUTH_REFRESH_SECONDS"
    )
    parsed = parse_float_or_none(raw)
    if isinstance(parsed, float) and parsed >= 0:
        return parsed
    return 1.0


def dashboard_reconcile_for_snapshot(runtime: Any, state: object) -> list[str]:
    refresh_seconds = dashboard_truth_refresh_seconds(runtime)
    run_id = str(getattr(state, "run_id", ""))
    if refresh_seconds > 0:
        now = time.monotonic()
        if runtime._dashboard_truth_cache_run_id == run_id and now < runtime._dashboard_truth_cache_expires_at:
            return list(runtime._dashboard_truth_cache_missing_services)

    failing_services = list(runtime._reconcile_state_truth(state))
    if refresh_seconds > 0:
        runtime._dashboard_truth_cache_run_id = run_id
        runtime._dashboard_truth_cache_expires_at = time.monotonic() + refresh_seconds
        runtime._dashboard_truth_cache_missing_services = list(failing_services)
    else:
        runtime._dashboard_truth_cache_run_id = None
        runtime._dashboard_truth_cache_expires_at = 0.0
        runtime._dashboard_truth_cache_missing_services = []
    return failing_services
