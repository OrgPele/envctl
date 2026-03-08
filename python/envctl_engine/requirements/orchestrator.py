from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from envctl_engine.requirements.common import is_bind_conflict
from envctl_engine.shared.reason_codes import (
    PortFailureReason,
    RequirementFailureReason,
    RequirementLifecycleReason,
    reason_code_to_string,
)


class FailureClass(str, Enum):
    BIND_CONFLICT_RETRYABLE = "bind_conflict_retryable"
    TRANSIENT_PROBE_TIMEOUT_RETRYABLE = "transient_probe_timeout_retryable"
    BOOTSTRAP_SOFT_FAILURE = "bootstrap_soft_failure"
    HARD_START_FAILURE = "hard_start_failure"


@dataclass(slots=True)
class RequirementOutcome:
    service_name: str
    success: bool
    requested_port: int
    final_port: int
    retries: int
    simulated: bool = False
    failure_class: FailureClass | None = None
    error: str | None = None
    reason_code: str | None = None
    container_name: str | None = None


class RequirementsOrchestrator:
    def classify_failure(self, service_name: str, error: str | None, *, strict: bool) -> FailureClass:
        if is_bind_conflict(error):
            return FailureClass.BIND_CONFLICT_RETRYABLE

        normalized = (error or "").lower()
        transient_tokens = (
            "timeout",
            "timed out",
            "probe",
            "no response",
            "connection refused",
            "temporarily unavailable",
        )
        if any(token in normalized for token in transient_tokens):
            return FailureClass.TRANSIENT_PROBE_TIMEOUT_RETRYABLE

        if service_name == "n8n" and ("404" in normalized or "setup endpoint" in normalized or "owner bootstrap" in normalized):
            if strict:
                return FailureClass.HARD_START_FAILURE
            return FailureClass.BOOTSTRAP_SOFT_FAILURE

        return FailureClass.HARD_START_FAILURE

    def reason_code_for_failure(
        self,
        service_name: str,
        failure_class: FailureClass,
        *,
        error: str | None = None,
    ) -> str:
        _ = error
        if failure_class == FailureClass.BIND_CONFLICT_RETRYABLE:
            return reason_code_to_string(PortFailureReason.PORT_IN_USE)
        if failure_class == FailureClass.TRANSIENT_PROBE_TIMEOUT_RETRYABLE:
            return reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE)
        if failure_class == FailureClass.BOOTSTRAP_SOFT_FAILURE:
            return reason_code_to_string(RequirementLifecycleReason.BOOTSTRAP_SOFT_FAILURE)
        if service_name == "postgres":
            return reason_code_to_string(RequirementFailureReason.DATABASE_CONNECTION_FAILED)
        if service_name == "redis":
            return reason_code_to_string(RequirementFailureReason.REDIS_CONNECTION_FAILED)
        if service_name == "supabase":
            return reason_code_to_string(RequirementFailureReason.SUPABASE_INIT_FAILED)
        if service_name == "n8n":
            return reason_code_to_string(RequirementFailureReason.N8N_INIT_FAILED)
        return reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE)

    def _next_rebind_port(
        self,
        *,
        current_port: int,
        reserve_next: Callable[[int], int],
    ) -> int:
        requested = max(current_port + 1, 1)
        reserved = reserve_next(requested)
        return max(reserved, requested)

    def _bind_conflict_guidance(
        self,
        *,
        service_name: str,
        port: int,
        retries: int,
        error: str | None,
    ) -> str:
        attempt_word = "attempt" if retries == 1 else "attempts"
        detail = (error or "bind conflict").strip() or "bind conflict"
        return (
            f"{detail}. Unable to bind {service_name} after {retries} deterministic rebind {attempt_word} "
            f"(last candidate port {port}). Resolve conflicting listeners or enable "
            "ENVCTL_REQUIREMENT_BIND_SAFE_CLEANUP=true to remove stale envctl-owned containers before retrying."
        )

    def start_requirement(
        self,
        *,
        service_name: str,
        port: int,
        start: Callable[[int], tuple[bool, str | None]],
        reserve_next: Callable[[int], int],
        max_retries: int = 3,
        strict: bool = False,
        max_bind_retries: int | None = None,
        max_transient_retries: int | None = None,
        on_retry: Callable[[str, int, int, int, FailureClass, str | None], None] | None = None,
    ) -> RequirementOutcome:
        bind_retry_budget = max_retries if max_bind_retries is None else max(max_bind_retries, 0)
        transient_retry_budget = max_retries if max_transient_retries is None else max(max_transient_retries, 0)
        current_port = port
        retries = 0
        bind_retries = 0
        transient_retries = 0

        while True:
            success, error = start(current_port)
            if success:
                return RequirementOutcome(
                    service_name=service_name,
                    success=True,
                    requested_port=port,
                    final_port=current_port,
                    retries=retries,
                )

            failure_class = self.classify_failure(service_name, error, strict=strict)
            reason_code = self.reason_code_for_failure(service_name, failure_class, error=error)
            if failure_class == FailureClass.BIND_CONFLICT_RETRYABLE and bind_retries < bind_retry_budget:
                failed_port = current_port
                retries += 1
                bind_retries += 1
                current_port = self._next_rebind_port(current_port=current_port, reserve_next=reserve_next)
                if on_retry is not None:
                    on_retry(service_name, failed_port, current_port, retries, failure_class, error)
                continue
            if (
                failure_class == FailureClass.TRANSIENT_PROBE_TIMEOUT_RETRYABLE
                and transient_retries < transient_retry_budget
            ):
                failed_port = current_port
                retries += 1
                transient_retries += 1
                if on_retry is not None:
                    on_retry(service_name, failed_port, current_port, retries, failure_class, error)
                continue

            final_error = error
            if failure_class == FailureClass.BIND_CONFLICT_RETRYABLE:
                reason_code = reason_code_to_string(RequirementLifecycleReason.BIND_CONFLICT_UNRESOLVED)
                final_error = self._bind_conflict_guidance(
                    service_name=service_name,
                    port=current_port,
                    retries=bind_retries,
                    error=error,
                )

            return RequirementOutcome(
                service_name=service_name,
                success=False,
                requested_port=port,
                final_port=current_port,
                retries=retries,
                failure_class=failure_class,
                error=final_error,
                reason_code=reason_code,
            )
