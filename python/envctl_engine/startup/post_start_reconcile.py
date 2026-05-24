from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any

from envctl_engine.startup.session import StartupSession


def reconcile_strict_truth_after_start(
    *,
    runtime: Any,
    session: StartupSession,
    build_run_state: Callable[[Any, StartupSession], Any],
    reconcile_state_truth: Callable[[Any], list[str]],
    emit_phase: Callable[..., None],
) -> None:
    if runtime.config.runtime_truth_mode != "strict":
        return
    if session.plan_agent_handoff_degraded:
        reconcile_started = time.monotonic()
        emit_phase(
            session,
            "post_start_reconcile",
            reconcile_started,
            status="skipped_degraded_handoff",
            missing_count=0,
        )
        runtime._emit(
            "state.reconcile",
            run_id=session.run_id,
            source="start.post_start",
            missing_count=0,
            missing_services=[],
            skipped=True,
            reason="plan_agent_handoff_degraded",
        )
        return
    run_state = build_run_state(runtime, session)
    reconcile_started = time.monotonic()
    degraded_services = reconcile_state_truth(run_state)
    emit_phase(
        session,
        "post_start_reconcile",
        reconcile_started,
        status="degraded" if degraded_services else "ok",
        missing_count=len(degraded_services),
    )
    runtime._emit(
        "state.reconcile",
        run_id=run_state.run_id,
        source="start.post_start",
        missing_count=len(degraded_services),
        missing_services=degraded_services,
    )
    if degraded_services:
        session.strict_truth_failed = True
        unique_services = sorted(set(degraded_services))
        raise RuntimeError("service truth degraded after startup: " + ", ".join(unique_services))
