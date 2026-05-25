from __future__ import annotations

from collections.abc import Callable, Mapping
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
from envctl_engine.shared.protocols import ProcessRuntime
from envctl_engine.startup.requirements_native_telemetry import (
    CommandTimingRunnerProxy,
    NativeAdapterTelemetryEmitter,
    classify_docker_stage,
    extract_probe_attempts,
)
from envctl_engine.startup.protocols import ProjectContextLike
from envctl_engine.startup.public_urls import browser_backend_url, resolve_public_host

__all__ = [
    "NativeAdapterStartResult",
    "classify_docker_stage",
    "docker_command_timing_enabled",
    "extract_probe_attempts",
    "requirements_trace_enabled",
    "start_requirement_with_native_adapter",
]


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
        process_runner = CommandTimingRunnerProxy(runtime.process_runner, sink=command_timings)

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
    summary = NativeAdapterTelemetryEmitter(
        runtime=runtime,
        context=context,
        service_name=service_name,
        port=port,
        result=result,
        trace_enabled=trace_enabled,
        command_timing_enabled=command_timing_enabled,
        command_timings=command_timings,
    ).emit()
    if result.success:
        return NativeAdapterStartResult(
            success=True,
            error=None,
            effective_port=summary.effective_port,
            port_adopted=summary.port_adopted,
            container_name=result.container_name,
        )
    return NativeAdapterStartResult(
        success=False,
        error=result.error or f"{service_name} adapter failed",
        effective_port=summary.effective_port,
        port_adopted=summary.port_adopted,
        container_name=result.container_name,
    )
