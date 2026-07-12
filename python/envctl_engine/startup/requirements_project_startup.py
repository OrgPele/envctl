from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from dataclasses import dataclass, field
import sys
import threading
import time
from typing import Any

from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.requirements.external import (
    dependency_external_mode,
    external_dependency_outcome,
    external_dependency_resources,
    external_dependency_url,
)
from envctl_engine.requirements.orchestrator import FailureClass, RequirementOutcome
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.runtime_context import resolve_port_allocator
from envctl_engine.shared.parsing import parse_bool, parse_int
from envctl_engine.startup.protocols import ProjectContextLike, StartupOrchestratorLike
from envctl_engine.startup.startup_progress import report_progress as report_progress_impl
from envctl_engine.startup.startup_progress import suppress_timing_output
from envctl_engine.state.models import RequirementsResult

REQUIREMENTS_PROGRESS_PROJECT_FLAG = "_requirements_progress_project"


def _has_reserved_ports(final_port: object, resources: dict[str, int]) -> bool:
    return (isinstance(final_port, int) and not isinstance(final_port, bool) and final_port > 0) or any(
        isinstance(port, int) and not isinstance(port, bool) and port > 0 for port in resources.values()
    )


def requirements_parallel_platform_default() -> bool:
    return sys.platform != "darwin"


def requirements_parallel_enabled(
    orchestrator: StartupOrchestratorLike,
    *,
    route: Route | None,
    enabled_count: int,
) -> bool:
    if enabled_count <= 1:
        return False
    if route is not None:
        route_value = route.flags.get("requirements_parallel")
        if isinstance(route_value, bool):
            return route_value
    rt = orchestrator.runtime
    raw_parallel = rt.env.get("ENVCTL_REQUIREMENTS_PARALLEL") or rt.config.raw.get("ENVCTL_REQUIREMENTS_PARALLEL")
    return parse_bool(raw_parallel, requirements_parallel_platform_default())


def format_requirements_progress_message(*, active: set[str], pending: set[str]) -> str:
    active_list = sorted(str(name).strip() for name in active if str(name).strip())
    pending_list = sorted(str(name).strip() for name in pending if str(name).strip())
    if active_list:
        message = "Loading requirements: " + ", ".join(active_list)
        if pending_list:
            message += " | queued: " + ", ".join(pending_list)
        return message
    if pending_list:
        return "Preparing requirements: " + ", ".join(pending_list)
    return "Preparing requirements..."


@dataclass(slots=True)
class RequirementProjectStarter:
    orchestrator: StartupOrchestratorLike
    context: ProjectContextLike
    mode: str
    route: Route | None = None
    report_progress_fn: Callable[..., None] | None = None
    suppress_timing_output_fn: Callable[[Route | None], bool] = suppress_timing_output
    requirements_timing_enabled_fn: Callable[[StartupOrchestratorLike, Route | None], bool] | None = None
    definitions: list[Any] = field(default_factory=dependency_definitions)
    failures: list[str] = field(default_factory=list, init=False)
    component_timings_ms: dict[str, float] = field(default_factory=dict, init=False)
    outcomes: dict[str, RequirementOutcome] = field(default_factory=dict, init=False)
    reserve_lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    progress_state_lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    pending_requirements: set[str] = field(default_factory=set, init=False)
    active_requirements: set[str] = field(default_factory=set, init=False)

    def execute(self) -> RequirementsResult:
        rt = self.orchestrator.runtime
        started = time.monotonic()
        if hook_result := self._maybe_handle_setup_hook():
            return hook_result

        enabled_lookup = self._enabled_lookup()
        external_lookup = self._external_lookup(enabled_lookup)
        enabled_definitions = [
            definition
            for definition in self.definitions
            if enabled_lookup[definition.id] and not external_lookup[definition.id]
        ]
        self.pending_requirements = {definition.id for definition in enabled_definitions}

        self._emit_progress()
        self._record_external_outcomes(external_lookup)
        self._record_skipped_outcomes()
        self._run_enabled_components(enabled_definitions)

        for outcome in self.outcomes.values():
            if not outcome.success:
                self.failures.append(f"{outcome.service_name}:{outcome.failure_class}:{outcome.error}")

        total_duration_ms = round((time.monotonic() - started) * 1000.0, 2)
        rt._emit(
            "requirements.timing.summary",
            project=self.context.name,
            duration_ms=total_duration_ms,
            components=self.component_timings_ms,
            failures=len(self.failures),
        )
        self._print_timing_summary(total_duration_ms)
        return RequirementsResult(
            project=self.context.name,
            components=self._build_components(enabled_lookup, external_lookup),
            health="healthy" if not self.failures else "degraded",
            failures=self.failures,
        )

    def _maybe_handle_setup_hook(self) -> RequirementsResult | None:
        rt = self.orchestrator.runtime
        if self.route is not None and self.route.flags.get("launch_dependencies") is False:
            return None
        setup_hook = rt._invoke_envctl_hook(context=self.context, hook_name="envctl_setup_infrastructure")
        if setup_hook.found and not setup_hook.success:
            self.failures.append(f"setup_hook:{setup_hook.error or 'failed'}")
            return RequirementsResult(
                project=self.context.name,
                components=self._hook_failure_components(),
                health="degraded",
                failures=self.failures,
            )
        if setup_hook.found and setup_hook.success:
            payload = setup_hook.payload if isinstance(setup_hook.payload, dict) else {}
            if bool(payload.get("skip_default_requirements")):
                return rt._requirements_result_from_hook_payload(
                    context=self.context,
                    mode=self.mode,
                    payload=payload,
                )
        return None

    def _hook_failure_components(self) -> dict[str, dict[str, object]]:
        rt = self.orchestrator.runtime
        components: dict[str, dict[str, object]] = {}
        for definition in self.definitions:
            plan = self._plan_for_dependency(definition.id)
            components[definition.id] = {
                "requested": plan.requested,
                "final": plan.final,
                "resources": self._resources_for_definition(definition),
                "retries": 0,
                "success": False,
                "simulated": False,
                "enabled": rt._requirement_enabled(definition.id, mode=self.mode, route=self.route),
            }
        return components

    def _enabled_lookup(self) -> dict[str, bool]:
        rt = self.orchestrator.runtime
        return {
            definition.id: bool(rt._requirement_enabled(definition.id, mode=self.mode, route=self.route))
            for definition in self.definitions
        }

    def _external_lookup(self, enabled_lookup: dict[str, bool]) -> dict[str, bool]:
        rt = self.orchestrator.runtime
        return {
            definition.id: bool(
                enabled_lookup[definition.id]
                and dependency_external_mode(rt, definition.id, mode=self.mode, route=self.route)
            )
            for definition in self.definitions
        }

    def _record_external_outcomes(self, external_lookup: dict[str, bool]) -> None:
        rt = self.orchestrator.runtime
        for definition in self.definitions:
            if not external_lookup[definition.id]:
                continue
            outcome = external_dependency_outcome(
                runtime=rt,
                definition=definition,
                plan=self._plan_for_dependency(definition.id),
            )
            self.component_timings_ms[definition.id] = 0.0
            rt._emit(
                "requirements.external",
                project=self.context.name,
                requirement=definition.id,
                success=outcome.success,
                url=external_dependency_url(rt, definition.id),
                error=outcome.error,
            )
            self._emit_component_timing(definition.id, outcome=outcome, enabled=True, duration_ms=0.0)
            self.outcomes[definition.id] = outcome

    def _record_skipped_outcomes(self) -> None:
        rt = self.orchestrator.runtime
        for definition in self.definitions:
            if definition.id in self.outcomes:
                continue
            if definition.id in self.pending_requirements:
                continue
            outcome = rt._skipped_requirement(definition.id, self._plan_for_dependency(definition.id))
            self.component_timings_ms[definition.id] = 0.0
            self._emit_component_timing(definition.id, outcome=outcome, enabled=False, duration_ms=0.0)
            self.outcomes[definition.id] = outcome

    def _run_enabled_components(self, enabled_definitions: list[Any]) -> None:
        parallel_enabled = requirements_parallel_enabled(
            self.orchestrator,
            route=self.route,
            enabled_count=len(enabled_definitions),
        )
        worker_count = self._worker_count(parallel_enabled=parallel_enabled, enabled_count=len(enabled_definitions))
        self.orchestrator.runtime._emit(
            "requirements.execution",
            project=self.context.name,
            mode="parallel" if parallel_enabled and worker_count > 1 else "sequential",
            workers=worker_count,
            enabled=sorted(definition.id for definition in enabled_definitions),
        )
        self._print_execution_mode(parallel_enabled=parallel_enabled, worker_count=worker_count)

        if parallel_enabled and worker_count > 1:
            self._run_components_parallel(enabled_definitions, worker_count=worker_count)
            return
        for definition in enabled_definitions:
            self.outcomes[definition.id] = self._run_component(
                definition.id,
                self._plan_for_dependency(definition.id),
                strict=self._strict_component(definition.id),
            )

    def _run_components_parallel(self, enabled_definitions: list[Any], *, worker_count: int) -> None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map: dict[concurrent.futures.Future[RequirementOutcome], str] = {}
            for definition in enabled_definitions:
                future = executor.submit(
                    self._run_component,
                    definition.id,
                    self._plan_for_dependency(definition.id),
                    strict=self._strict_component(definition.id),
                )
                future_map[future] = definition.id
            for future in concurrent.futures.as_completed(future_map):
                definition_id = future_map[future]
                try:
                    self.outcomes[definition_id] = future.result()
                except Exception as exc:  # noqa: BLE001
                    self.outcomes[definition_id] = self._failed_outcome(
                        definition_id,
                        self._plan_for_dependency(definition_id),
                        exc,
                    )

    def _run_component(self, component: str, plan: object, *, strict: bool = False) -> RequirementOutcome:
        started = time.monotonic()
        with self.progress_state_lock:
            self.pending_requirements.discard(component)
            self.active_requirements.add(component)
            self._emit_progress_safely()
        try:
            try:
                outcome = self.orchestrator.runtime._start_requirement_component(
                    self.context,
                    component,
                    plan,
                    self._reserve_next,
                    strict=strict,
                    route=self.route,
                )
            except Exception as exc:  # noqa: BLE001
                outcome = self._failed_outcome(component, plan, exc)
            duration_ms = round((time.monotonic() - started) * 1000.0, 2)
            self.component_timings_ms[component] = duration_ms
            try:
                self._emit_component_timing(component, outcome=outcome, enabled=True, duration_ms=duration_ms)
            except Exception:  # noqa: BLE001
                pass
            return outcome
        finally:
            with self.progress_state_lock:
                self.active_requirements.discard(component)
                self._emit_progress_safely()

    @staticmethod
    def _failed_outcome(component: str, plan: object, error: BaseException) -> RequirementOutcome:
        return RequirementOutcome(
            service_name=component,
            success=False,
            requested_port=int(getattr(plan, "requested", 0) or 0),
            final_port=int(getattr(plan, "final", 0) or 0),
            retries=0,
            failure_class=FailureClass.HARD_START_FAILURE,
            error=str(error),
        )

    def _emit_progress_safely(self) -> None:
        try:
            self._emit_progress()
        except Exception:  # noqa: BLE001
            return

    def _build_components(
        self,
        enabled_lookup: dict[str, bool],
        external_lookup: dict[str, bool],
    ) -> dict[str, dict[str, object]]:
        rt = self.orchestrator.runtime
        components: dict[str, dict[str, object]] = {}
        for definition in self.definitions:
            outcome = self.outcomes[definition.id]
            resources = (
                external_dependency_resources(rt, definition)
                if external_lookup[definition.id]
                else self._resources_for_definition(definition, outcome)
            )
            components[definition.id] = {
                "requested": outcome.requested_port,
                "final": outcome.final_port,
                "resources": resources,
                "retries": outcome.retries,
                "success": outcome.success,
                "simulated": outcome.simulated,
                "enabled": enabled_lookup[definition.id],
                "reason_code": outcome.reason_code,
                "failure_class": outcome.failure_class.value if getattr(outcome, "failure_class", None) else None,
                "error": outcome.error,
                "container_name": outcome.container_name,
            }
            if (
                enabled_lookup[definition.id]
                and not external_lookup[definition.id]
                and _has_reserved_ports(
                    outcome.final_port,
                    resources,
                )
            ):
                raw_session_id = getattr(resolve_port_allocator(rt), "session_id", None)
                session_id = raw_session_id.strip() if isinstance(raw_session_id, str) else ""
                if session_id:
                    components[definition.id]["port_lock_session"] = session_id
            if external_lookup[definition.id]:
                components[definition.id].update(
                    {
                        "external": True,
                        "runtime_status": "healthy" if outcome.success else "unreachable",
                        "external_url": external_dependency_url(rt, definition.id),
                    }
                )
        return components

    def _emit_progress(self) -> None:
        if not self.pending_requirements and not self.active_requirements:
            return
        if self.route is None:
            return
        progress_project_flag = self.route.flags.get(REQUIREMENTS_PROGRESS_PROJECT_FLAG)
        progress_project = (
            str(progress_project_flag).strip() if progress_project_flag is not None else self.context.name
        )
        progress_message = format_requirements_progress_message(
            active=self.active_requirements,
            pending=self.pending_requirements,
        )
        if self.report_progress_fn is not None:
            self.report_progress_fn(self.route, progress_message, project=progress_project or self.context.name)
            return
        report_progress_impl(
            self.orchestrator.runtime,
            self.route,
            progress_lock=getattr(self.orchestrator, "_progress_lock"),
            last_progress_message_by_project=getattr(self.orchestrator, "_last_progress_message_by_project"),
            message=progress_message,
            project=progress_project or self.context.name,
        )

    def _emit_component_timing(
        self,
        component: str,
        *,
        outcome: RequirementOutcome,
        enabled: bool,
        duration_ms: float,
    ) -> None:
        self.orchestrator.runtime._emit(
            "requirements.timing.component",
            project=self.context.name,
            requirement=component,
            duration_ms=duration_ms,
            enabled=enabled,
            success=bool(getattr(outcome, "success", False)),
            retries=int(getattr(outcome, "retries", 0)),
            final_port=getattr(outcome, "final_port", None),
            failure_class=str(getattr(outcome, "failure_class", "")),
        )

    def _print_execution_mode(self, *, parallel_enabled: bool, worker_count: int) -> None:
        if not self._timing_enabled() or self.suppress_timing_output_fn(self.route):
            return
        print(
            "Requirements execution for "
            f"{self.context.name}: "
            f"{'parallel' if parallel_enabled and worker_count > 1 else 'sequential'} "
            f"(workers={worker_count})"
        )

    def _print_timing_summary(self, total_duration_ms: float) -> None:
        if not self._timing_enabled() or self.suppress_timing_output_fn(self.route):
            return
        component_parts = " ".join(
            f"{name}={self.component_timings_ms.get(name, 0.0):.1f}ms"
            for name in (definition.id for definition in self.definitions)
        )
        print(f"Requirements timing for {self.context.name}: {component_parts} total={total_duration_ms:.1f}ms")

    def _worker_count(self, *, parallel_enabled: bool, enabled_count: int) -> int:
        rt = self.orchestrator.runtime
        raw_workers = rt.env.get("ENVCTL_REQUIREMENTS_PARALLEL_MAX") or rt.config.raw.get(
            "ENVCTL_REQUIREMENTS_PARALLEL_MAX"
        )
        worker_limit = max(parse_int(raw_workers, 4), 1)
        return min(worker_limit, enabled_count) if parallel_enabled else 1

    def _resources_for_definition(self, definition: Any, outcome: RequirementOutcome | None = None) -> dict[str, int]:
        resources: dict[str, int] = {}
        for resource in definition.resources:
            plan = self.context.ports.get(resource.legacy_port_key)
            if plan is None:
                continue
            value = getattr(plan, "final", None)
            if isinstance(value, int) and value > 0:
                resources[resource.name] = value
        if outcome is not None and definition.resources:
            primary_name = definition.resources[0].name
            final_port = getattr(outcome, "final_port", None)
            if isinstance(final_port, int) and final_port > 0:
                resources[primary_name] = final_port
                resources["primary"] = final_port
                resources["requested"] = int(getattr(outcome, "requested_port", final_port) or final_port)
        return resources

    def _reserve_next(self, port: int) -> int:
        with self.reserve_lock:
            return resolve_port_allocator(self.orchestrator.runtime).reserve_next(
                port,
                owner=f"{self.context.name}:requirements",
            )

    def _plan_for_dependency(self, dependency_id: str) -> object:
        for definition in self.definitions:
            if definition.id == dependency_id:
                return self.context.ports[definition.resources[0].legacy_port_key]
        raise KeyError(dependency_id)

    def _strict_component(self, component: str) -> bool:
        return bool(component == "n8n" and self.orchestrator.runtime.config.strict_n8n_bootstrap)

    def _timing_enabled(self) -> bool:
        if self.requirements_timing_enabled_fn is None:
            return False
        return self.requirements_timing_enabled_fn(self.orchestrator, self.route)


def start_requirements_for_project(
    orchestrator: StartupOrchestratorLike,
    context: ProjectContextLike,
    *,
    mode: str,
    route: Route | None = None,
    report_progress_fn: Callable[..., None] | None = None,
    suppress_timing_output_fn: Callable[[Route | None], bool] = suppress_timing_output,
    requirements_timing_enabled_fn: Callable[[StartupOrchestratorLike, Route | None], bool] | None = None,
) -> RequirementsResult:
    return RequirementProjectStarter(
        orchestrator=orchestrator,
        context=context,
        mode=mode,
        route=route,
        report_progress_fn=report_progress_fn,
        suppress_timing_output_fn=suppress_timing_output_fn,
        requirements_timing_enabled_fn=requirements_timing_enabled_fn,
    ).execute()
