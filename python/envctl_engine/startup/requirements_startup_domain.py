from __future__ import annotations

# pyright: reportUnusedFunction=false

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from envctl_engine.runtime.command_resolution import CommandResolutionError
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
    self._emit("requirements.start", project=context.name, service=name, port=plan.final)
    command_source = "unknown"
    pending_supabase_fingerprint: str | None = None
    native_effective_port: int | None = None
    native_port_adopted = False
    native_container_name: str | None = None

    def start(port: int) -> tuple[bool, str | None]:
        remaining = self._conflict_remaining.get(name, 0)
        if remaining > 0:
            self._conflict_remaining[name] = remaining - 1
            return False, "bind: address already in use"

        nonlocal pending_supabase_fingerprint
        if name == "supabase":
            contract = evaluate_managed_supabase_reliability_contract()
            network_ok = not any("network" in error.lower() for error in contract.errors)
            auth_ok = not any(
                token in error
                for token in (
                    "GOTRUE_DB_DATABASE_URL",
                    "GOTRUE_DB_NAMESPACE",
                    "DB_NAMESPACE",
                    "bootstrap",
                )
                for error in contract.errors
            )
            self._emit(
                "supabase.network.contract", project=context.name, ok=network_ok, compose=str(contract.compose_path)
            )
            self._emit(
                "supabase.auth_namespace.contract", project=context.name, ok=auth_ok, compose=str(contract.compose_path)
            )
            if not contract.ok:
                return False, "; ".join(contract.errors)

            fingerprint_path = self._supabase_fingerprint_path(context.name)
            previous = read_supabase_fingerprint(fingerprint_path)
            compatible_fingerprints = set(getattr(contract, "compatible_fingerprints", ()) or ())
            if previous is not None and previous != contract.fingerprint and previous not in compatible_fingerprints:
                self._emit(
                    "supabase.fingerprint.changed",
                    project=context.name,
                    previous=previous,
                    current=contract.fingerprint,
                )
                if not self._supabase_auto_reinit_enabled():
                    self._emit("supabase.reinit.required", project=context.name, fingerprint_path=str(fingerprint_path))
                    return False, self._supabase_reinit_required_message()
                reinit_error = self._run_supabase_reinit(
                    project_root=context.root,
                    project_name=context.name,
                    db_port=port,
                    public_port=_context_port(context, "supabase_api"),
                )
                if reinit_error is not None:
                    return False, reinit_error
                self._emit("supabase.reinit.executed", project=context.name, fingerprint_path=str(fingerprint_path))
            elif previous is not None and previous in compatible_fingerprints:
                self._emit(
                    "supabase.fingerprint.compatible",
                    project=context.name,
                    previous=previous,
                    current=contract.fingerprint,
                    fingerprint_path=str(fingerprint_path),
                )
            pending_supabase_fingerprint = contract.fingerprint

        nonlocal command_source
        nonlocal native_effective_port
        nonlocal native_port_adopted
        nonlocal native_container_name
        adapter_result = self._start_requirement_with_native_adapter(
            context=context,
            service_name=name,
            port=port,
            route=route,
        )
        if adapter_result is not None:
            command_source = "native_adapter"
            native_effective_port = (
                int(adapter_result.effective_port) if isinstance(adapter_result.effective_port, int) else None
            )
            native_port_adopted = bool(adapter_result.port_adopted)
            native_container_name = adapter_result.container_name
            return adapter_result.success, adapter_result.error

        command, resolved_source = self._requirement_command_resolved(
            service_name=name,
            port=port,
            project_root=context.root,
        )
        command_source = resolved_source
        result = self.process_runner.run(
            command,
            cwd=context.root,
            env=self._command_env(port=port, extra=self._runtime_env_overrides(route)),
            timeout=30.0,
        )
        if result.returncode == 0:
            if self._wait_for_requirement_listener(port):
                return True, None
            return False, f"probe timeout waiting for readiness on port {port}"
        error = (result.stderr or result.stdout or f"exit:{result.returncode}").strip()
        return False, error

    def on_requirement_retry(
        service_name: str,
        failed_port: int,
        retry_port: int,
        attempt: int,
        failure_class: FailureClass,
        error: str | None,
    ) -> None:
        reason_code = self.requirements.reason_code_for_failure(service_name, failure_class, error=error)
        self._emit(
            "requirements.retry",
            project=context.name,
            service=service_name,
            failed_port=failed_port,
            retry_port=retry_port,
            attempt=attempt,
            failure_class=str(failure_class.value),
            reason=reason_code,
            reason_code=reason_code,
            error=(error or "").strip() or None,
        )

    try:
        outcome = self.requirements.start_requirement(
            service_name=name,
            port=plan.final,
            start=start,
            reserve_next=reserve_next,
            max_retries=3,
            strict=strict,
            max_bind_retries=self._requirement_bind_max_retries(),
            on_retry=on_requirement_retry,
        )
    except CommandResolutionError as exc:
        if self.config.requirements_strict:
            raise
        outcome = RequirementOutcome(
            service_name=name,
            success=False,
            requested_port=plan.requested,
            final_port=plan.final,
            retries=0,
            failure_class=FailureClass.HARD_START_FAILURE,
            error=str(exc),
        )
    if outcome.success and isinstance(native_effective_port, int) and native_effective_port > 0:
        outcome.final_port = native_effective_port
    if native_container_name:
        outcome.container_name = native_container_name
    if outcome.final_port != plan.final:
        update_source = "adopt_existing" if native_port_adopted and outcome.success else "retry"
        self.port_planner.update_final_port(plan, outcome.final_port, source=update_source)
        plan.retries = max(plan.retries, outcome.retries)
    else:
        plan.retries = max(plan.retries, outcome.retries)
    if outcome.success:
        if native_port_adopted and isinstance(outcome.final_port, int) and outcome.final_port > 0:
            self._emit(
                "requirements.port_adopted",
                project=context.name,
                service=name,
                adopted_port=outcome.final_port,
                requested_port=plan.requested,
            )
        self._emit("requirements.healthy", project=context.name, service=name, final_port=outcome.final_port)
        if name == "supabase" and pending_supabase_fingerprint:
            write_supabase_fingerprint(
                self._supabase_fingerprint_path(context.name),
                fingerprint=pending_supabase_fingerprint,
                project_root=context.root,
            )
            self._emit("supabase.signup.probe", project=context.name, status="skipped")
    else:
        failure_class = (
            outcome.failure_class.value if isinstance(outcome.failure_class, FailureClass) else outcome.failure_class
        )
        reason_code = outcome.reason_code
        if reason_code is None and isinstance(outcome.failure_class, FailureClass):
            reason_code = self.requirements.reason_code_for_failure(name, outcome.failure_class, error=outcome.error)
        self._emit(
            "requirements.failure_class",
            project=context.name,
            service=name,
            failure_class=failure_class,
            reason=reason_code,
            reason_code=reason_code,
            error=outcome.error,
        )
    _ = command_source
    return outcome


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
