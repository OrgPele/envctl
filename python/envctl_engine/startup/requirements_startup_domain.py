from __future__ import annotations

# pyright: reportUnusedFunction=false

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from envctl_engine.runtime.command_resolution import CommandResolutionError
from envctl_engine.runtime.command_router import Route
from envctl_engine.requirements.core import dependency_definition
from envctl_engine.state.models import PortPlan
from envctl_engine.shared.parsing import parse_bool, parse_float
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


class ProjectContextLike(Protocol):
    name: str
    root: Path


class _CommandTimingRunnerProxy:
    """Proxy process runner that records command timing and return codes."""

    def __init__(self, base_runner: object, *, sink: list[dict[str, object]]) -> None:
        self._base_runner = base_runner
        self._sink = sink

    def run(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> object:
        command = [str(part) for part in cmd]
        started = time.monotonic()
        result = self._base_runner.run(cmd, cwd=cwd, env=env, timeout=timeout)  # type: ignore[attr-defined]
        duration_ms = round((time.monotonic() - started) * 1000.0, 2)
        stderr = str(getattr(result, "stderr", "") or "")
        stdout = str(getattr(result, "stdout", "") or "")
        returncode = int(getattr(result, "returncode", 1))
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


def _coerce_returncode(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


@dataclass(slots=True)
class _NativeAdapterStartResult:
    success: bool
    error: str | None = None
    effective_port: int | None = None
    port_adopted: bool = False
    container_name: str | None = None


def _requirements_trace_enabled(self: Any, route: Route | None) -> bool:
    raw = self.env.get("ENVCTL_DEBUG_REQUIREMENTS_TRACE") or self.config.raw.get("ENVCTL_DEBUG_REQUIREMENTS_TRACE")
    if parse_bool(raw, False):
        return True
    if route is not None and (bool(route.flags.get("debug_ui")) or bool(route.flags.get("debug_ui_deep"))):
        return True
    mode = (
        str(self.env.get("ENVCTL_DEBUG_UI_MODE") or self.config.raw.get("ENVCTL_DEBUG_UI_MODE") or "").strip().lower()
    )
    return mode in {"deep"}


def _docker_command_timing_enabled(self: Any, route: Route | None) -> bool:
    raw = self.env.get("ENVCTL_DEBUG_DOCKER_COMMAND_TIMING") or self.config.raw.get(
        "ENVCTL_DEBUG_DOCKER_COMMAND_TIMING"
    )
    if parse_bool(raw, False):
        return True
    return _requirements_trace_enabled(self, route)


def _classify_docker_stage(command: list[str]) -> str:
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


def _extract_probe_attempts(command_timings: list[dict[str, object]], *, service_name: str) -> list[dict[str, object]]:
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


def _start_requirement_component(
    self: Any,
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
            if previous is not None and previous != contract.fingerprint:
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
                    project_root=context.root, project_name=context.name, db_port=port
                )
                if reinit_error is not None:
                    return False, reinit_error
                self._emit("supabase.reinit.executed", project=context.name, fingerprint_path=str(fingerprint_path))
            pending_supabase_fingerprint = contract.fingerprint

        nonlocal command_source
        nonlocal native_effective_port
        nonlocal native_port_adopted
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


def _requirement_listener_timeout_seconds(self: Any) -> float:
    raw = self._command_override_value("ENVCTL_REQUIREMENT_LISTENER_TIMEOUT_SECONDS")
    parsed = parse_float(raw, 10.0)
    if parsed is None or parsed <= 0:
        return 10.0
    return parsed


def _start_requirement_with_native_adapter(
    self: Any,
    *,
    context: ProjectContextLike,
    service_name: str,
    port: int,
    route: Route | None = None,
) -> _NativeAdapterStartResult | None:
    if not self.config.requirements_strict:
        return None
    try:
        definition = dependency_definition(service_name)
    except Exception:
        return None
    override_key = f"ENVCTL_REQUIREMENT_{service_name.upper()}_CMD"
    if self._command_override_value(override_key):
        return None
    if not self._command_exists("docker"):
        return None
    native_starter = {
        "postgres": start_postgres_container,
        "redis": start_redis_container,
        "n8n": start_n8n_container,
        "supabase": start_supabase_stack,
    }.get(service_name, definition.native_starter)
    if not callable(native_starter):
        return None

    trace_enabled = _requirements_trace_enabled(self, route)
    command_timing_enabled = _docker_command_timing_enabled(self, route)
    command_timings: list[dict[str, object]] = []
    process_runner = self.process_runner
    if command_timing_enabled:
        process_runner = _CommandTimingRunnerProxy(self.process_runner, sink=command_timings)

    command_env = self._command_env(port=port, extra=self._runtime_env_overrides(route))
    if service_name == "postgres":
        db_user = self._command_override_value("DB_USER") or "postgres"
        db_password = self._command_override_value("DB_PASSWORD") or "postgres"
        db_name = self._command_override_value("DB_NAME") or "postgres"
        result = native_starter(
            process_runner=process_runner,
            project_root=context.root,
            project_name=context.name,
            port=port,
            db_user=db_user,
            db_password=db_password,
            db_name=db_name,
            env=command_env,
        )
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
        command_env = dict(command_env)
        command_env.setdefault("ENVCTL_SUPABASE_DB_START_NATIVE", "true")
        result = native_starter(
            process_runner=process_runner,
            project_root=context.root,
            project_name=context.name,
            db_port=port,
            runtime_root=self.runtime_root,
            env=command_env,
        )

    stage_events_raw = result.stage_events if isinstance(result.stage_events, list) else []
    stage_events = [item for item in stage_events_raw if isinstance(item, dict)]
    stage_durations_ms = result.stage_durations_ms if isinstance(result.stage_durations_ms, dict) else {}
    listener_wait_ms = float(result.listener_wait_ms or 0.0)
    probe_attempts = _extract_probe_attempts(command_timings, service_name=service_name)
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
        for index, stage_item in enumerate(stage_events, start=1):
            self._emit(
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
        self._emit(
            "requirements.adapter.listener_wait",
            project=context.name,
            service=service_name,
            port=port,
            listener_wait_ms=round(listener_wait_ms, 2),
        )
        restart_used = any(str(item.get("stage", "")).startswith("probe.retry.restart") for item in stage_events)
        recreate_used = bool(result.container_recreated) or any(
            str(item.get("stage", "")).startswith("probe.retry.recreate") for item in stage_events
        )
        self._emit(
            "requirements.adapter.retry_path",
            project=context.name,
            service=service_name,
            port=port,
            restart_used=restart_used,
            recreate_used=recreate_used,
            stage_count=len(stage_events),
        )
        for attempt in probe_attempts:
            self._emit(
                "requirements.adapter.probe_attempt",
                project=context.name,
                service=service_name,
                port=port,
                attempt=int(attempt.get("attempt", 0) or 0),
                duration_ms=round(float(attempt.get("duration_ms", 0.0) or 0.0), 2),
                returncode=_coerce_returncode(attempt.get("returncode", 1)),
                timed_out=bool(attempt.get("timed_out", False)),
            )
        if mismatch_action is not None:
            self._emit(
                "requirements.adapter.port_mismatch",
                project=context.name,
                service=service_name,
                requested_port=mismatch_requested_port,
                existing_port=mismatch_existing_port,
                action=mismatch_action,
                adopted=port_adopted,
                effective_port=effective_port,
            )

    if command_timing_enabled:
        for index, command_item in enumerate(command_timings, start=1):
            raw_command = command_item.get("command")
            command_tokens = [str(part) for part in raw_command] if isinstance(raw_command, list) else []
            self._emit(
                "requirements.adapter.command_timing",
                project=context.name,
                service=service_name,
                port=port,
                order=index,
                stage=_classify_docker_stage(command_tokens),
                command=command_tokens,
                duration_ms=round(float(command_item.get("duration_ms", 0.0) or 0.0), 2),
                timeout_s=command_item.get("timeout_s"),
                returncode=_coerce_returncode(command_item.get("returncode", 1)),
                timed_out=bool(command_item.get("timed_out", False)),
            )

    self._emit(
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
        return _NativeAdapterStartResult(
            success=True,
            error=None,
            effective_port=effective_port,
            port_adopted=port_adopted,
            container_name=result.container_name,
        )
    return _NativeAdapterStartResult(
        success=False,
        error=result.error or f"{service_name} adapter failed",
        effective_port=effective_port,
        port_adopted=port_adopted,
        container_name=result.container_name,
    )
