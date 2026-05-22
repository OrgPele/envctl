from __future__ import annotations

from collections.abc import Callable
import time

from envctl_engine.startup.requirements_execution import maybe_prewarm_docker
from envctl_engine.startup.session import StartupSession
from envctl_engine.startup.session_lifecycle import emit_startup_phase


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


def prepare_startup_execution_with_runtime(runtime: object, session: StartupSession) -> None:
    runtime_facade = type("_StartupExecutionPreparationRuntimeFacade", (), {"runtime": runtime})()
    prepare_startup_execution(
        session=session,
        maybe_prewarm_docker=lambda *, route, mode: maybe_prewarm_docker(runtime_facade, route=route, mode=mode),
        emit_phase=lambda *args, **kwargs: emit_startup_phase(runtime, *args, **kwargs),
    )
