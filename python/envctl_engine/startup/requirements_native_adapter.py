from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from envctl_engine.requirements.common import ContainerStartResult
from envctl_engine.requirements.core import dependency_definition
from envctl_engine.requirements.n8n import start_n8n_container
from envctl_engine.requirements.postgres import start_postgres_container
from envctl_engine.requirements.redis import start_redis_container
from envctl_engine.requirements.supabase import start_supabase_stack
from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.parsing import parse_bool
from envctl_engine.shared.protocols import CommandResult, ProcessRuntime
from envctl_engine.startup.protocols import ProjectContextLike
from envctl_engine.startup.public_urls import browser_backend_url, resolve_public_host


class _RequirementsConfig(Protocol):
    raw: Mapping[str, str]
    requirements_strict: bool


class _NativeAdapterRuntime(Protocol):
    env: Mapping[str, str]
    config: _RequirementsConfig
    process_runner: ProcessRuntime
    runtime_root: Path

    def _emit(self, event: str, **payload: object) -> None: ...
    def _command_env(self, *, port: int, extra: Mapping[str, str] | None = None) -> dict[str, str]: ...
    def _runtime_env_overrides(self, route: Route | None) -> dict[str, str]: ...
    def _command_override_value(self, key: str) -> str | None: ...
    def _command_exists(self, command: str) -> bool: ...


class _CommandTimingRunnerProxy:
    """Proxy process runner that records command timing and return codes."""

    def __init__(self, base_runner: ProcessRuntime, *, sink: list[dict[str, object]]) -> None:
        self._base_runner = base_runner
        self._sink = sink

    def run(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        command = [str(part) for part in cmd]
        started = time.monotonic()
        result = self._base_runner.run(cmd, cwd=cwd, env=env, timeout=timeout)
        duration_ms = round((time.monotonic() - started) * 1000.0, 2)
        stderr = str(result.stderr or "")
        stdout = str(result.stdout or "")
        returncode = int(result.returncode)
        timed_out = bool(returncode == 124 or "timed out" in stderr.lower() or "timed out" in stdout.lower())
        self._sink.append(
            {
                "command": command,
                "duration_ms": duration_ms,
                "timeout_s": timeout,
                "returncode": returncode,
                "timed_out": timed_out,
            }
        )
        return result

    def __getattr__(self, name: str) -> object:
        return getattr(self._base_runner, name)


@dataclass(slots=True)
class NativeAdapterStartResult:
    success: bool
    error: str | None = None
    effective_port: int | None = None
    port_adopted: bool = False
    container_name: str | None = None


NativeStarter = Callable[..., ContainerStartResult]


def requirements_trace_enabled(runtime: _NativeAdapterRuntime, route: Route | None) -> bool:
    raw = runtime.env.get("ENVCTL_DEBUG_REQUIREMENTS_TRACE") or runtime.config.raw.get(
        "ENVCTL_DEBUG_REQUIREMENTS_TRACE"
    )
    if parse_bool(raw, False):
        return True
    if route is not None and (bool(route.flags.get("debug_ui")) or bool(route.flags.get("debug_ui_deep"))):
        return True
    mode = (
        str(runtime.env.get("ENVCTL_DEBUG_UI_MODE") or runtime.config.raw.get("ENVCTL_DEBUG_UI_MODE") or "")
        .strip()
        .lower()
    )
    return mode in {"deep"}


def docker_command_timing_enabled(runtime: _NativeAdapterRuntime, route: Route | None) -> bool:
    raw = runtime.env.get("ENVCTL_DEBUG_DOCKER_COMMAND_TIMING") or runtime.config.raw.get(
        "ENVCTL_DEBUG_DOCKER_COMMAND_TIMING"
    )
    if parse_bool(raw, False):
        return True
    return requirements_trace_enabled(runtime, route)


def classify_docker_stage(command: list[str]) -> str:
    if len(command) < 2 or command[0] != "docker":
        return "other"
    sub = command[1].strip().lower()
    if sub in {"ps", "inspect", "port"}:
        return "discover"
    if sub == "run":
        return "create"
    if sub == "start":
        return "start"
    if sub == "restart":
        return "restart"
    if sub == "exec":
        return "probe"
    if sub in {"stop", "rm"}:
        return "recreate"
    return "other"


def extract_probe_attempts(command_timings: list[dict[str, object]], *, service_name: str) -> list[dict[str, object]]:
    attempts: list[dict[str, object]] = []
    for item in command_timings:
        command = item.get("command")
        if not isinstance(command, list):
            continue
        tokens = [str(part).strip().lower() for part in command]
        if len(tokens) < 3 or tokens[0] != "docker" or tokens[1] != "exec":
            continue
        is_probe = False
        if service_name == "postgres":
            is_probe = "pg_isready" in tokens
        elif service_name == "redis":
            is_probe = "redis-cli" in tokens and "ping" in tokens
        elif service_name == "n8n":
            # n8n adapter uses listener-only probe path; keep for future-proofing.
            is_probe = "curl" in tokens or "wget" in tokens
        if not is_probe:
            continue
        attempts.append(
            {
                "duration_ms": float(item.get("duration_ms", 0.0) or 0.0),
                "returncode": _coerce_returncode(item.get("returncode", 1)),
                "timed_out": bool(item.get("timed_out", False)),
                "command": command,
            }
        )
    for index, attempt in enumerate(attempts, start=1):
        attempt["attempt"] = index
    return attempts


def start_requirement_with_native_adapter(
    runtime: _NativeAdapterRuntime,
    *,
    context: ProjectContextLike,
    service_name: str,
    port: int,
    route: Route | None = None,
    native_starters: Mapping[str, NativeStarter] | None = None,
    public_port: int | None = None,
) -> NativeAdapterStartResult | None:
    if not runtime.config.requirements_strict:
        return None
    try:
        definition = dependency_definition(service_name)
    except Exception:
        return None
    override_key = f"ENVCTL_REQUIREMENT_{service_name.upper()}_CMD"
    if runtime._command_override_value(override_key):
        return None
    if not runtime._command_exists("docker"):
        return None

    starter_overrides = dict(native_starters or {})
    native_starter = starter_overrides.get(
        service_name,
        {
            "postgres": start_postgres_container,
            "redis": start_redis_container,
            "n8n": start_n8n_container,
            "supabase": start_supabase_stack,
        }.get(service_name, definition.native_starter),
    )
    if not callable(native_starter):
        return None

    trace_enabled = requirements_trace_enabled(runtime, route)
    command_timing_enabled = docker_command_timing_enabled(runtime, route)
    command_timings: list[dict[str, object]] = []
    process_runner = runtime.process_runner
    if command_timing_enabled:
        process_runner = _CommandTimingRunnerProxy(runtime.process_runner, sink=command_timings)

    command_env = runtime._command_env(port=port, extra=runtime._runtime_env_overrides(route))
    if service_name == "postgres":
        result = _start_postgres(native_starter, runtime, process_runner, context, port, command_env)
    elif service_name == "redis":
        result = native_starter(
            process_runner=process_runner,
            project_root=context.root,
            project_name=context.name,
            port=port,
            env=command_env,
        )
    elif service_name == "n8n":
        result = native_starter(
            process_runner=process_runner,
            project_root=context.root,
            project_name=context.name,
            port=port,
            env=command_env,
        )
    else:
        result = _start_supabase(native_starter, runtime, process_runner, context, port, command_env, public_port)

    return _project_native_result(
        runtime,
        context=context,
        service_name=service_name,
        port=port,
        result=result,
        trace_enabled=trace_enabled,
        command_timing_enabled=command_timing_enabled,
        command_timings=command_timings,
    )


def _start_postgres(
    native_starter: NativeStarter,
    runtime: _NativeAdapterRuntime,
    process_runner: ProcessRuntime,
    context: ProjectContextLike,
    port: int,
    command_env: Mapping[str, str],
) -> ContainerStartResult:
    db_user = runtime._command_override_value("DB_USER") or "postgres"
    db_password = runtime._command_override_value("DB_PASSWORD") or "postgres"
    db_name = runtime._command_override_value("DB_NAME") or "postgres"
    return native_starter(
        process_runner=process_runner,
        project_root=context.root,
        project_name=context.name,
        port=port,
        db_user=db_user,
        db_password=db_password,
        db_name=db_name,
        env=command_env,
    )


def _start_supabase(
    native_starter: NativeStarter,
    runtime: _NativeAdapterRuntime,
    process_runner: ProcessRuntime,
    context: ProjectContextLike,
    port: int,
    command_env: Mapping[str, str],
    public_port: int | None,
) -> ContainerStartResult:
    env = dict(command_env)
    if isinstance(public_port, int) and public_port > 0:
        env.setdefault("SUPABASE_PUBLIC_PORT", str(public_port))
        env.setdefault("SUPABASE_API_PORT", str(public_port))
        env.setdefault(
            "SUPABASE_PUBLIC_URL",
            browser_backend_url(
                host=resolve_public_host(env=getattr(runtime, "env", None), config=getattr(runtime, "config", None)),
                port=public_port,
            ),
        )
    return native_starter(
        process_runner=process_runner,
        project_root=context.root,
        project_name=context.name,
        db_port=port,
        public_port=public_port,
        runtime_root=runtime.runtime_root,
        env=env,
    )


def _project_native_result(
    runtime: _NativeAdapterRuntime,
    *,
    context: ProjectContextLike,
    service_name: str,
    port: int,
    result: ContainerStartResult,
    trace_enabled: bool,
    command_timing_enabled: bool,
    command_timings: list[dict[str, object]],
) -> NativeAdapterStartResult:
    stage_events_raw = result.stage_events if isinstance(result.stage_events, list) else []
    stage_events = [item for item in stage_events_raw if isinstance(item, dict)]
    stage_durations_ms = result.stage_durations_ms if isinstance(result.stage_durations_ms, dict) else {}
    listener_wait_ms = float(result.listener_wait_ms or 0.0)
    result_probe_attempts_raw = result.probe_attempts if isinstance(result.probe_attempts, list) else []
    result_probe_attempts = [item for item in result_probe_attempts_raw if isinstance(item, dict)]
    probe_attempts = result_probe_attempts or extract_probe_attempts(command_timings, service_name=service_name)
    effective_port = (
        int(result.effective_port)
        if isinstance(result.effective_port, int) and result.effective_port > 0
        else int(port)
    )
    port_adopted = bool(result.port_adopted)
    mismatch_requested_port = (
        int(result.port_mismatch_requested_port)
        if isinstance(result.port_mismatch_requested_port, int) and result.port_mismatch_requested_port > 0
        else int(port)
    )
    mismatch_existing_port = (
        int(result.port_mismatch_existing_port)
        if isinstance(result.port_mismatch_existing_port, int) and result.port_mismatch_existing_port > 0
        else None
    )
    mismatch_action = str(result.port_mismatch_action or "").strip().lower() or None

    if trace_enabled:
        _emit_trace_events(
            runtime,
            context=context,
            service_name=service_name,
            port=port,
            stage_events=stage_events,
            listener_wait_ms=listener_wait_ms,
            result=result,
            probe_attempts=probe_attempts,
            mismatch_action=mismatch_action,
            mismatch_requested_port=mismatch_requested_port,
            mismatch_existing_port=mismatch_existing_port,
            effective_port=effective_port,
            port_adopted=port_adopted,
        )

    if command_timing_enabled:
        _emit_command_timing_events(
            runtime,
            context=context,
            service_name=service_name,
            port=port,
            command_timings=command_timings,
        )

    runtime._emit(
        "requirements.adapter",
        project=context.name,
        service=service_name,
        container=result.container_name,
        success=result.success,
        port=port,
        effective_port=effective_port,
        port_adopted=port_adopted,
        reason=result.reason_code,
        reason_code=result.reason_code,
        failure_class=result.failure_class,
        stage_durations_ms=stage_durations_ms,
        docker_command_count=len(command_timings),
        probe_attempt_count=len(probe_attempts),
        listener_wait_ms=round(listener_wait_ms, 2),
        container_reused=bool(result.container_reused),
        container_recreated=bool(result.container_recreated),
    )
    if result.success:
        return NativeAdapterStartResult(
            success=True,
            error=None,
            effective_port=effective_port,
            port_adopted=port_adopted,
            container_name=result.container_name,
        )
    return NativeAdapterStartResult(
        success=False,
        error=result.error or f"{service_name} adapter failed",
        effective_port=effective_port,
        port_adopted=port_adopted,
        container_name=result.container_name,
    )


def _emit_trace_events(
    runtime: _NativeAdapterRuntime,
    *,
    context: ProjectContextLike,
    service_name: str,
    port: int,
    stage_events: list[dict[str, object]],
    listener_wait_ms: float,
    result: ContainerStartResult,
    probe_attempts: list[dict[str, object]],
    mismatch_action: str | None,
    mismatch_requested_port: int,
    mismatch_existing_port: int | None,
    effective_port: int,
    port_adopted: bool,
) -> None:
    for index, stage_item in enumerate(stage_events, start=1):
        runtime._emit(
            "requirements.adapter.stage",
            project=context.name,
            service=service_name,
            port=port,
            order=index,
            stage=str(stage_item.get("stage", "")),
            reason=stage_item.get("reason"),
            detail=stage_item.get("detail"),
            elapsed_ms=stage_item.get("elapsed_ms"),
        )
    runtime._emit(
        "requirements.adapter.listener_wait",
        project=context.name,
        service=service_name,
        port=port,
        listener_wait_ms=round(listener_wait_ms, 2),
    )
    restart_used = any(
        str(item.get("stage", "")).startswith(("probe.retry.restart", "supabase.auth.restart")) for item in stage_events
    )
    recreate_used = bool(result.container_recreated) or any(
        str(item.get("stage", "")).startswith(("probe.retry.recreate", "supabase.auth.recreate"))
        for item in stage_events
    )
    runtime._emit(
        "requirements.adapter.retry_path",
        project=context.name,
        service=service_name,
        port=port,
        restart_used=restart_used,
        recreate_used=recreate_used,
        stage_count=len(stage_events),
    )
    for attempt in probe_attempts:
        runtime._emit(
            "requirements.adapter.probe_attempt",
            project=context.name,
            service=service_name,
            port=port,
            attempt=_coerce_returncode(attempt.get("attempt", 0)),
            phase=attempt.get("phase"),
            action=attempt.get("action"),
            duration_ms=round(_coerce_float(attempt.get("duration_ms", 0.0)), 2),
            returncode=_coerce_returncode(attempt.get("returncode", 1)),
            timed_out=bool(attempt.get("timed_out", False)),
            error=attempt.get("error"),
        )
    if mismatch_action is not None:
        runtime._emit(
            "requirements.adapter.port_mismatch",
            project=context.name,
            service=service_name,
            requested_port=mismatch_requested_port,
            existing_port=mismatch_existing_port,
            action=mismatch_action,
            adopted=port_adopted,
            effective_port=effective_port,
        )


def _emit_command_timing_events(
    runtime: _NativeAdapterRuntime,
    *,
    context: ProjectContextLike,
    service_name: str,
    port: int,
    command_timings: list[dict[str, object]],
) -> None:
    for index, command_item in enumerate(command_timings, start=1):
        raw_command = command_item.get("command")
        command_tokens = [str(part) for part in raw_command] if isinstance(raw_command, list) else []
        runtime._emit(
            "requirements.adapter.command_timing",
            project=context.name,
            service=service_name,
            port=port,
            order=index,
            stage=classify_docker_stage(command_tokens),
            command=command_tokens,
            duration_ms=round(_coerce_float(command_item.get("duration_ms", 0.0)), 2),
            timeout_s=command_item.get("timeout_s"),
            returncode=_coerce_returncode(command_item.get("returncode", 1)),
            timed_out=bool(command_item.get("timed_out", False)),
        )


def _coerce_returncode(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


def _coerce_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
