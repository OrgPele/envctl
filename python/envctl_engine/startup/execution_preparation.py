from __future__ import annotations

from collections.abc import Callable
import time

from envctl_engine.startup.session import StartupSession


def prepare_startup_execution(
    *,
    session: StartupSession,
    maybe_prewarm_docker: Callable[..., None],
    emit_phase: Callable[..., None],
) -> None:
    route = session.effective_route
    prewarm_started = time.monotonic()
    maybe_prewarm_docker(route=route, mode=session.runtime_mode)
    emit_phase(session, "docker_prewarm", prewarm_started, status="ok")
