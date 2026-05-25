from __future__ import annotations

# pyright: reportUnusedFunction=false

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import PortPlan
from envctl_engine.shared.protocols import PortAllocator, ProcessRuntime
from envctl_engine.shared.parsing import parse_float
from envctl_engine.requirements.n8n import start_n8n_container
from envctl_engine.requirements.postgres import start_postgres_container
from envctl_engine.requirements.redis import start_redis_container
from envctl_engine.requirements.supabase import (
    evaluate_managed_supabase_reliability_contract,
    read_fingerprint as read_supabase_fingerprint,
    start_supabase_stack,
    write_fingerprint as write_supabase_fingerprint,
)
from envctl_engine.requirements.orchestrator import FailureClass, RequirementOutcome
from envctl_engine.startup.requirements_component_startup import (
    start_requirement_component as _component_start_requirement_component,
)
from envctl_engine.startup.requirements_native_adapter import (
    NativeAdapterStartResult as _NativeAdapterStartResult,
    classify_docker_stage as _classify_docker_stage,
    docker_command_timing_enabled as _docker_command_timing_enabled,
    extract_probe_attempts as _extract_probe_attempts,
    requirements_trace_enabled as _requirements_trace_enabled,
    start_requirement_with_native_adapter as _native_start_requirement_with_native_adapter,
)
from envctl_engine.startup.protocols import ProjectContextLike

__all__ = [
    "_NativeAdapterStartResult",
    "_classify_docker_stage",
    "_docker_command_timing_enabled",
    "_extract_probe_attempts",
    "_requirements_trace_enabled",
    "_context_port",
    "_start_requirement_component",
    "_start_requirement_with_native_adapter",
]


class _RequirementsHelpers(Protocol):
    def reason_code_for_failure(
        self, service_name: str, failure_class: FailureClass, *, error: str | None = None
    ) -> str: ...
    def start_requirement(
        self,
        *,
        service_name: str,
        port: int,
        start: Callable[[int], tuple[bool, str | None]],
        reserve_next: Callable[[int], int],
        max_retries: int = 3,
        strict: bool = False,
        max_bind_retries: int = 0,
        on_retry: Callable[[str, int, int, int, FailureClass, str | None], None] | None = None,
    ) -> RequirementOutcome: ...


class _RequirementsConfig(Protocol):
    raw: Mapping[str, str]
    requirements_strict: bool


class _RequirementsRuntime(Protocol):
    env: Mapping[str, str]
    config: _RequirementsConfig
    process_runner: ProcessRuntime
    port_planner: PortAllocator
    requirements: _RequirementsHelpers
    runtime_root: Path
    _conflict_remaining: dict[str, int]

    def _emit(self, event: str, **payload: object) -> None: ...
    def _supabase_fingerprint_path(self, project_name: str) -> Path: ...
    def _supabase_auto_reinit_enabled(self) -> bool: ...
    def _supabase_reinit_required_message(self) -> str: ...
    def _run_supabase_reinit(
        self, *, project_root: Path, project_name: str, db_port: int, public_port: int | None = None
    ) -> str | None: ...
    def _requirement_command_resolved(
        self, *, service_name: str, port: int, project_root: Path
    ) -> tuple[list[str], str]: ...
    def _command_env(self, *, port: int, extra: Mapping[str, str] | None = None) -> dict[str, str]: ...
    def _runtime_env_overrides(self, route: Route | None) -> dict[str, str]: ...
    def _wait_for_requirement_listener(self, port: int) -> bool: ...
    def _requirement_bind_max_retries(self) -> int: ...
    def _requirement_listener_timeout_seconds(self) -> float: ...
    def _command_override_value(self, key: str) -> str | None: ...
    def _command_exists(self, command: str) -> bool: ...
    def _start_requirement_with_native_adapter(
        self,
        *,
        context: ProjectContextLike,
        service_name: str,
        port: int,
        route: Route | None = None,
    ) -> _NativeAdapterStartResult | None: ...


def _start_requirement_component(
    self: _RequirementsRuntime,
    context: ProjectContextLike,
    name: str,
    plan: PortPlan,
    reserve_next: Callable[[int], int],
    *,
    strict: bool = False,
    route: Route | None = None,
) -> RequirementOutcome:
    return _component_start_requirement_component(
        self,
        context=context,
        name=name,
        plan=plan,
        reserve_next=reserve_next,
        strict=strict,
        route=route,
        supabase_contract_evaluator=evaluate_managed_supabase_reliability_contract,
        read_fingerprint=read_supabase_fingerprint,
        write_fingerprint=write_supabase_fingerprint,
        context_port=_context_port,
    )


def _wait_for_requirement_listener(self, port: int) -> bool:
    if port <= 0:
        return False
    timeout = self._requirement_listener_timeout_seconds()
    return bool(self.process_runner.wait_for_port(port, timeout=timeout))


def _requirement_listener_timeout_seconds(self: _RequirementsRuntime) -> float:
    raw = self._command_override_value("ENVCTL_REQUIREMENT_LISTENER_TIMEOUT_SECONDS")
    parsed = parse_float(raw, 10.0)
    if parsed is None or parsed <= 0:
        return 10.0
    return parsed


def _context_port(context: ProjectContextLike, name: str) -> int | None:
    ports = getattr(context, "ports", {})
    if not isinstance(ports, dict):
        return None
    plan = ports.get(name)
    value = getattr(plan, "final", None)
    return int(value) if isinstance(value, int) and value > 0 else None


def _start_requirement_with_native_adapter(
    self: _RequirementsRuntime,
    *,
    context: ProjectContextLike,
    service_name: str,
    port: int,
    route: Route | None = None,
) -> _NativeAdapterStartResult | None:
    return _native_start_requirement_with_native_adapter(
        self,
        context=context,
        service_name=service_name,
        port=port,
        route=route,
        native_starters={
            "postgres": start_postgres_container,
            "redis": start_redis_container,
            "n8n": start_n8n_container,
            "supabase": start_supabase_stack,
        },
        public_port=_context_port(context, "supabase_api"),
    )
