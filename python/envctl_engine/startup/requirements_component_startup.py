from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.requirements.orchestrator import FailureClass, RequirementOutcome
from envctl_engine.requirements.supabase import (
    evaluate_managed_supabase_reliability_contract,
    read_fingerprint as read_supabase_fingerprint,
    write_fingerprint as write_supabase_fingerprint,
)
from envctl_engine.runtime.command_resolution import CommandResolutionError
from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.protocols import PortAllocator, ProcessRuntime
from envctl_engine.startup.protocols import ProjectContextLike
from envctl_engine.startup.requirements_native_adapter import NativeAdapterStartResult
from envctl_engine.state.models import PortPlan


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
    requirements_strict: bool


class _RequirementsRuntime(Protocol):
    config: _RequirementsConfig
    process_runner: ProcessRuntime
    port_planner: PortAllocator
    requirements: _RequirementsHelpers
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
    def _start_requirement_with_native_adapter(
        self,
        *,
        context: ProjectContextLike,
        service_name: str,
        port: int,
        route: Route | None = None,
    ) -> NativeAdapterStartResult | None: ...


NativeAdapterStart = Callable[..., NativeAdapterStartResult | None]
SupabaseContractEvaluator = Callable[[], object]
ReadFingerprint = Callable[[Path], str | None]
WriteFingerprint = Callable[..., None]
ContextPort = Callable[[ProjectContextLike, str], int | None]


@dataclass(slots=True)
class RequirementComponentHooks:
    native_adapter_start: NativeAdapterStart | None = None
    supabase_contract_evaluator: SupabaseContractEvaluator = evaluate_managed_supabase_reliability_contract
    read_supabase_fingerprint: ReadFingerprint = read_supabase_fingerprint
    write_supabase_fingerprint: WriteFingerprint = write_supabase_fingerprint
    context_port: ContextPort | None = None


class RequirementComponentStarter:
    def __init__(
        self,
        runtime: _RequirementsRuntime,
        *,
        context: ProjectContextLike,
        name: str,
        plan: PortPlan,
        reserve_next: Callable[[int], int],
        strict: bool,
        route: Route | None,
        hooks: RequirementComponentHooks,
    ) -> None:
        self.runtime = runtime
        self.context = context
        self.name = name
        self.plan = plan
        self.reserve_next = reserve_next
        self.strict = strict
        self.route = route
        self.hooks = hooks
        self.pending_supabase_fingerprint: str | None = None
        self.native_effective_port: int | None = None
        self.native_port_adopted = False
        self.native_container_name: str | None = None

    def start(self) -> RequirementOutcome:
        self.runtime._emit("requirements.start", project=self.context.name, service=self.name, port=self.plan.final)
        try:
            outcome = self.runtime.requirements.start_requirement(
                service_name=self.name,
                port=self.plan.final,
                start=self._start_once,
                reserve_next=self.reserve_next,
                max_retries=3,
                strict=self.strict,
                max_bind_retries=self.runtime._requirement_bind_max_retries(),
                on_retry=self._on_retry,
            )
        except CommandResolutionError as exc:
            if self.runtime.config.requirements_strict:
                raise
            outcome = RequirementOutcome(
                service_name=self.name,
                success=False,
                requested_port=self.plan.requested,
                final_port=self.plan.final,
                retries=0,
                failure_class=FailureClass.HARD_START_FAILURE,
                error=str(exc),
            )
        return self._finalize_outcome(outcome)

    def _start_once(self, port: int) -> tuple[bool, str | None]:
        conflict_error = self._maybe_return_synthetic_bind_conflict()
        if conflict_error is not None:
            return False, conflict_error
        if self.name == "supabase":
            ok, error = self._prepare_supabase_contract(port)
            if not ok:
                return False, error

        adapter_result = self._start_native_adapter(port)
        if adapter_result is not None:
            self.native_effective_port = (
                int(adapter_result.effective_port) if isinstance(adapter_result.effective_port, int) else None
            )
            self.native_port_adopted = bool(adapter_result.port_adopted)
            self.native_container_name = adapter_result.container_name
            return adapter_result.success, adapter_result.error
        return self._start_configured_command(port)

    def _maybe_return_synthetic_bind_conflict(self) -> str | None:
        remaining = self.runtime._conflict_remaining.get(self.name, 0)
        if remaining <= 0:
            return None
        self.runtime._conflict_remaining[self.name] = remaining - 1
        return "bind: address already in use"

    def _prepare_supabase_contract(self, port: int) -> tuple[bool, str | None]:
        contract = self.hooks.supabase_contract_evaluator()
        errors = [str(error) for error in getattr(contract, "errors", ()) or ()]
        network_ok = not any("network" in error.lower() for error in errors)
        auth_ok = not any(
            token in error
            for token in (
                "GOTRUE_DB_DATABASE_URL",
                "GOTRUE_DB_NAMESPACE",
                "DB_NAMESPACE",
                "bootstrap",
            )
            for error in errors
        )
        compose_path = str(getattr(contract, "compose_path", ""))
        self.runtime._emit("supabase.network.contract", project=self.context.name, ok=network_ok, compose=compose_path)
        self.runtime._emit(
            "supabase.auth_namespace.contract",
            project=self.context.name,
            ok=auth_ok,
            compose=compose_path,
        )
        if not bool(getattr(contract, "ok", False)):
            return False, "; ".join(errors)

        fingerprint = str(getattr(contract, "fingerprint", ""))
        fingerprint_path = self.runtime._supabase_fingerprint_path(self.context.name)
        previous = self.hooks.read_supabase_fingerprint(fingerprint_path)
        compatible_fingerprints = set(getattr(contract, "compatible_fingerprints", ()) or ())
        if previous is not None and previous != fingerprint and previous not in compatible_fingerprints:
            self.runtime._emit(
                "supabase.fingerprint.changed",
                project=self.context.name,
                previous=previous,
                current=fingerprint,
            )
            if not self.runtime._supabase_auto_reinit_enabled():
                self.runtime._emit(
                    "supabase.reinit.required",
                    project=self.context.name,
                    fingerprint_path=str(fingerprint_path),
                )
                return False, self.runtime._supabase_reinit_required_message()
            reinit_error = self.runtime._run_supabase_reinit(
                project_root=self.context.root,
                project_name=self.context.name,
                db_port=port,
                public_port=self._context_port("supabase_api"),
            )
            if reinit_error is not None:
                return False, reinit_error
            self.runtime._emit(
                "supabase.reinit.executed",
                project=self.context.name,
                fingerprint_path=str(fingerprint_path),
            )
        elif previous is not None and previous in compatible_fingerprints:
            self.runtime._emit(
                "supabase.fingerprint.compatible",
                project=self.context.name,
                previous=previous,
                current=fingerprint,
                fingerprint_path=str(fingerprint_path),
            )
        self.pending_supabase_fingerprint = fingerprint
        return True, None

    def _start_native_adapter(self, port: int) -> NativeAdapterStartResult | None:
        start_native = self.hooks.native_adapter_start
        if start_native is None:
            start_native = self.runtime._start_requirement_with_native_adapter
        return start_native(
            context=self.context,
            service_name=self.name,
            port=port,
            route=self.route,
        )

    def _start_configured_command(self, port: int) -> tuple[bool, str | None]:
        command, _resolved_source = self.runtime._requirement_command_resolved(
            service_name=self.name,
            port=port,
            project_root=self.context.root,
        )
        result = self.runtime.process_runner.run(
            command,
            cwd=self.context.root,
            env=self.runtime._command_env(port=port, extra=self.runtime._runtime_env_overrides(self.route)),
            timeout=30.0,
        )
        if result.returncode == 0:
            if self.runtime._wait_for_requirement_listener(port):
                return True, None
            return False, f"probe timeout waiting for readiness on port {port}"
        error = (result.stderr or result.stdout or f"exit:{result.returncode}").strip()
        return False, error

    def _on_retry(
        self,
        service_name: str,
        failed_port: int,
        retry_port: int,
        attempt: int,
        failure_class: FailureClass,
        error: str | None,
    ) -> None:
        if retry_port != failed_port:
            self._release_failed_requirement_port(failed_port)
        reason_code = self.runtime.requirements.reason_code_for_failure(service_name, failure_class, error=error)
        self.runtime._emit(
            "requirements.retry",
            project=self.context.name,
            service=service_name,
            failed_port=failed_port,
            retry_port=retry_port,
            attempt=attempt,
            failure_class=str(failure_class.value),
            reason=reason_code,
            reason_code=reason_code,
            error=(error or "").strip() or None,
        )

    def _release_failed_requirement_port(self, port: int) -> None:
        release = getattr(self.runtime.port_planner, "release", None)
        if not callable(release):
            return
        resource_keys = {
            resource.legacy_port_key
            for definition in dependency_definitions()
            if definition.id == self.name
            for resource in definition.resources
        }
        for owner_suffix in (*sorted(resource_keys), "requirements"):
            try:
                release(port, owner=f"{self.context.name}:{owner_suffix}")
            except TypeError:
                release(port)
                return

    def _finalize_outcome(self, outcome: RequirementOutcome) -> RequirementOutcome:
        if outcome.success and isinstance(self.native_effective_port, int) and self.native_effective_port > 0:
            outcome.final_port = self.native_effective_port
        if self.native_container_name:
            outcome.container_name = self.native_container_name
        self._update_plan_from_outcome(outcome)
        if outcome.success:
            self._emit_success(outcome)
        else:
            self._emit_failure(outcome)
        return outcome

    def _update_plan_from_outcome(self, outcome: RequirementOutcome) -> None:
        if outcome.final_port != self.plan.final:
            update_source = "adopt_existing" if self.native_port_adopted and outcome.success else "retry"
            self.runtime.port_planner.update_final_port(self.plan, outcome.final_port, source=update_source)
        self.plan.retries = max(self.plan.retries, outcome.retries)

    def _emit_success(self, outcome: RequirementOutcome) -> None:
        if self.native_port_adopted and isinstance(outcome.final_port, int) and outcome.final_port > 0:
            self.runtime._emit(
                "requirements.port_adopted",
                project=self.context.name,
                service=self.name,
                adopted_port=outcome.final_port,
                requested_port=self.plan.requested,
            )
        self.runtime._emit(
            "requirements.healthy",
            project=self.context.name,
            service=self.name,
            final_port=outcome.final_port,
        )
        if self.name == "supabase" and self.pending_supabase_fingerprint:
            self.hooks.write_supabase_fingerprint(
                self.runtime._supabase_fingerprint_path(self.context.name),
                fingerprint=self.pending_supabase_fingerprint,
                project_root=self.context.root,
            )
            self.runtime._emit("supabase.signup.probe", project=self.context.name, status="skipped")

    def _emit_failure(self, outcome: RequirementOutcome) -> None:
        failure_class = (
            outcome.failure_class.value if isinstance(outcome.failure_class, FailureClass) else outcome.failure_class
        )
        reason_code = outcome.reason_code
        if reason_code is None and isinstance(outcome.failure_class, FailureClass):
            reason_code = self.runtime.requirements.reason_code_for_failure(
                self.name,
                outcome.failure_class,
                error=outcome.error,
            )
        self.runtime._emit(
            "requirements.failure_class",
            project=self.context.name,
            service=self.name,
            failure_class=failure_class,
            reason=reason_code,
            reason_code=reason_code,
            error=outcome.error,
        )

    def _context_port(self, name: str) -> int | None:
        if self.hooks.context_port is not None:
            return self.hooks.context_port(self.context, name)
        ports = getattr(self.context, "ports", {})
        if not isinstance(ports, dict):
            return None
        plan = ports.get(name)
        value = getattr(plan, "final", None)
        return int(value) if isinstance(value, int) and value > 0 else None


def start_requirement_component(
    runtime: _RequirementsRuntime,
    context: ProjectContextLike,
    name: str,
    plan: PortPlan,
    reserve_next: Callable[[int], int],
    *,
    strict: bool = False,
    route: Route | None = None,
    native_adapter_start: NativeAdapterStart | None = None,
    supabase_contract_evaluator: SupabaseContractEvaluator = evaluate_managed_supabase_reliability_contract,
    read_fingerprint: ReadFingerprint = read_supabase_fingerprint,
    write_fingerprint: WriteFingerprint = write_supabase_fingerprint,
    context_port: ContextPort | None = None,
) -> RequirementOutcome:
    hooks = RequirementComponentHooks(
        native_adapter_start=native_adapter_start,
        supabase_contract_evaluator=supabase_contract_evaluator,
        read_supabase_fingerprint=read_fingerprint,
        write_supabase_fingerprint=write_fingerprint,
        context_port=context_port,
    )
    return RequirementComponentStarter(
        runtime,
        context=context,
        name=name,
        plan=plan,
        reserve_next=reserve_next,
        strict=strict,
        route=route,
        hooks=hooks,
    ).start()
