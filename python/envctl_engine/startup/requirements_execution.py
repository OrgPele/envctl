from __future__ import annotations

import re
import time
from collections.abc import Callable

from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.parsing import parse_bool, parse_int
from envctl_engine.startup.protocols import ProjectContextLike, StartupOrchestratorLike
from envctl_engine.startup.requirements_project_startup import (
    REQUIREMENTS_PROGRESS_PROJECT_FLAG as _REQUIREMENTS_PROGRESS_PROJECT_FLAG,
    format_requirements_progress_message as _format_requirements_progress_message,
    requirements_parallel_enabled as _requirements_parallel_enabled,
    requirements_parallel_platform_default as _requirements_parallel_platform_default,
    start_requirements_for_project as _start_requirements_for_project_impl,
)
from envctl_engine.startup.startup_progress import suppress_timing_output
from envctl_engine.startup.startup_selection_support import restart_include_requirements
from envctl_engine.state.lookup import call_state_loader
from envctl_engine.state.models import RequirementsResult
from envctl_engine.state.project_runtime import requirements_for_project

_DOCKER_SOCKET_PATTERNS = (
    re.compile(r"unix://(?P<path>[^\s;]+docker\.sock)"),
    re.compile(r"dial unix (?P<path>[^\s:;]+docker\.sock)"),
)
REQUIREMENTS_PROGRESS_PROJECT_FLAG = _REQUIREMENTS_PROGRESS_PROJECT_FLAG
format_requirements_progress_message = _format_requirements_progress_message
requirements_parallel_enabled = _requirements_parallel_enabled
requirements_parallel_platform_default = _requirements_parallel_platform_default


def requirements_failure_message(project_name: str, requirements: RequirementsResult) -> str:
    failed_components: list[str] = []
    docker_failed_components: list[str] = []
    for definition in dependency_definitions():
        component = requirements.component(definition.id)
        if not bool(component.get("enabled", False)) or bool(component.get("success", False)):
            continue
        failed_components.append(definition.id)
        error = str(component.get("error") or "")
        if _docker_daemon_unavailable(error):
            docker_failed_components.append(definition.id)
    if failed_components and len(docker_failed_components) == len(failed_components):
        services = ", ".join(docker_failed_components)
        return f"Docker is not running. Docker is required for {project_name} dependencies: {services}."
    return f"Requirements unavailable for {project_name}: " + ", ".join(requirements.failures)


def requirements_for_restart_context(
    orchestrator: StartupOrchestratorLike,
    *,
    context: ProjectContextLike,
    mode: str,
    route: Route | None,
) -> RequirementsResult:
    rt = orchestrator.runtime
    if route is None:
        return orchestrator.start_requirements_for_project(context, mode=mode, route=route)
    if not bool(route.flags.get("_restart_request")):
        return orchestrator.start_requirements_for_project(context, mode=mode, route=route)
    if restart_include_requirements(route):
        return orchestrator.start_requirements_for_project(context, mode=mode, route=route)

    previous = call_state_loader(
        rt._try_load_existing_state,
        mode=mode,
        strict_mode_match=True,
        project_names=[context.name],
    )
    if previous is not None:
        existing = requirements_for_project(previous, context.name)
        if isinstance(existing, RequirementsResult):
            rt._emit(
                "requirements.restart.reuse",
                project=context.name,
                include_requirements=False,
            )
            return existing

    rt._emit(
        "requirements.restart.reuse_missing",
        project=context.name,
        include_requirements=False,
    )
    return orchestrator.start_requirements_for_project(context, mode=mode, route=route)


def start_requirements_for_project(
    orchestrator: StartupOrchestratorLike,
    context: ProjectContextLike,
    *,
    mode: str,
    route: Route | None = None,
    report_progress_fn: Callable[..., None] | None = None,
    suppress_timing_output_fn: Callable[[Route | None], bool] = suppress_timing_output,
) -> RequirementsResult:
    return _start_requirements_for_project_impl(
        orchestrator,
        context,
        mode=mode,
        route=route,
        report_progress_fn=report_progress_fn,
        suppress_timing_output_fn=suppress_timing_output_fn,
        requirements_timing_enabled_fn=requirements_timing_enabled,
    )


def requirements_timing_enabled(orchestrator: StartupOrchestratorLike, route: Route | None) -> bool:
    rt = orchestrator.runtime
    raw_force = rt.env.get("ENVCTL_DEBUG_RESTORE_TIMING") or rt.config.raw.get("ENVCTL_DEBUG_RESTORE_TIMING")
    if bool(raw_force) and str(raw_force).strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if route is not None and (bool(route.flags.get("debug_ui")) or bool(route.flags.get("debug_ui_deep"))):
        return True
    raw_mode = (rt.env.get("ENVCTL_DEBUG_UI_MODE") or rt.config.raw.get("ENVCTL_DEBUG_UI_MODE") or "").strip().lower()
    return raw_mode in {"standard", "deep"}


def docker_prewarm_enabled(orchestrator: StartupOrchestratorLike, route: Route | None) -> bool:
    _ = route
    rt = orchestrator.runtime
    raw = rt.env.get("ENVCTL_DOCKER_PREWARM") or rt.config.raw.get("ENVCTL_DOCKER_PREWARM")
    return parse_bool(raw, True)


def docker_prewarm_timeout_seconds(orchestrator: StartupOrchestratorLike, route: Route | None) -> int:
    _ = route
    rt = orchestrator.runtime
    raw = rt.env.get("ENVCTL_DOCKER_PREWARM_TIMEOUT_SECONDS") or rt.config.raw.get(
        "ENVCTL_DOCKER_PREWARM_TIMEOUT_SECONDS"
    )
    value = parse_int(raw, 10)
    return max(value, 1)


def prewarm_requires_startup_requirements(
    orchestrator: StartupOrchestratorLike, *, mode: str, route: Route | None
) -> bool:
    rt = orchestrator.runtime
    for definition in dependency_definitions():
        if bool(rt._requirement_enabled(definition.id, mode=mode, route=route)):
            return True
    return False


def maybe_prewarm_docker(orchestrator: StartupOrchestratorLike, *, route: Route | None, mode: str) -> None:
    rt = orchestrator.runtime
    if not docker_prewarm_enabled(orchestrator, route):
        rt._emit("requirements.docker_prewarm", used=False, reason="disabled")
        return
    if not prewarm_requires_startup_requirements(orchestrator, mode=mode, route=route):
        rt._emit("requirements.docker_prewarm", used=False, reason="no_enabled_requirements")
        return
    if not rt._command_exists("docker"):
        rt._emit("requirements.docker_prewarm", used=False, reason="docker_missing")
        return
    timeout_s = docker_prewarm_timeout_seconds(orchestrator, route)
    started = time.monotonic()
    result = rt.process_runner.run(["docker", "ps"], timeout=float(timeout_s))
    duration_ms = round((time.monotonic() - started) * 1000.0, 2)
    returncode = int(result.returncode)
    stderr = str(result.stderr or "")
    stdout = str(result.stdout or "")
    timed_out = bool(returncode == 124 or "timed out" in stderr.lower() or "timed out" in stdout.lower())
    rt._emit(
        "requirements.docker_prewarm",
        used=True,
        command=["docker", "ps"],
        timeout_s=timeout_s,
        duration_ms=duration_ms,
        returncode=returncode,
        timed_out=timed_out,
        success=returncode == 0 and not timed_out,
    )


def startup_breakdown_enabled(orchestrator: StartupOrchestratorLike, route: Route | None) -> bool:
    rt = orchestrator.runtime
    raw = rt.env.get("ENVCTL_DEBUG_STARTUP_BREAKDOWN") or rt.config.raw.get("ENVCTL_DEBUG_STARTUP_BREAKDOWN")
    if parse_bool(raw, False):
        return True
    if route is not None and (bool(route.flags.get("debug_ui")) or bool(route.flags.get("debug_ui_deep"))):
        return True
    raw_mode = (rt.env.get("ENVCTL_DEBUG_UI_MODE") or rt.config.raw.get("ENVCTL_DEBUG_UI_MODE") or "").strip().lower()
    return raw_mode in {"deep"}


def _docker_daemon_unavailable(error: str) -> bool:
    normalized = error.strip().lower()
    if not normalized:
        return False
    docker_markers = (
        "failed to connect to the docker api",
        "cannot connect to the docker daemon",
        "is the docker daemon running",
        "error during connect",
    )
    if not any(marker in normalized for marker in docker_markers):
        return False
    return "docker.sock" in normalized or "docker daemon" in normalized


def _docker_socket_path(error: str) -> str | None:
    for pattern in _DOCKER_SOCKET_PATTERNS:
        match = pattern.search(error)
        if match is not None:
            return match.group("path")
    return None
