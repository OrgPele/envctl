from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, cast

from envctl_engine.runtime.service_manager import ServiceCleanupError, ServiceStartDescriptor
from envctl_engine.runtime.service_truth_diagnostics import service_listener_failure_class
from envctl_engine.shared.reason_codes import ServiceFailureReason
from envctl_engine.startup.service_execution_policy import ordered_service_layers
from envctl_engine.startup.service_execution_records import PreparedServiceLaunch
from envctl_engine.startup.session import unconfirmed_service_names
from envctl_engine.state.models import PortPlan, ServiceRecord


@dataclass(slots=True)
class ServiceAttachRunner:
    runtime: Any
    process_runtime: Any
    port_allocator: Any
    project_name: str
    project_root: Path
    backend_plan: PortPlan
    frontend_plan: PortPlan
    backend_cwd: Path
    frontend_cwd: Path
    backend_log_path: str
    frontend_log_path: str
    backend_env_extra: dict[str, str]
    frontend_env_extra: dict[str, str]
    command_env_builder: Callable[..., dict[str, str]]
    prepared_launches: Mapping[str, PreparedServiceLaunch]
    selected_service_types: set[str]
    additional_services: tuple[Any, ...]
    backend_listener_expected: bool
    rebound_delta: int
    _active_service_ports: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _rebound_launch_ports: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    def start(
        self,
        *,
        attach_parallel: bool,
        on_service_retry: Callable[[str, int, int, int, str | None], None],
    ) -> dict[str, ServiceRecord]:
        descriptors = self._service_descriptors()
        self._active_service_ports = {
            descriptor.service_type: descriptor.requested_port
            for descriptor in descriptors
            if descriptor.requested_port > 0
        }

        def release_failed_port_then_report(
            service_type: str,
            failed_port: int,
            retry_port: int,
            attempt: int,
            error: str | None,
        ) -> None:
            self._release_failed_service_port(service_type, failed_port)
            self._release_rebound_launch_port(service_type)
            if retry_port > 0:
                self._active_service_ports[service_type] = retry_port
            on_service_retry(service_type, failed_port, retry_port, attempt, error)

        try:
            if hasattr(self.runtime.services, "process_runner"):
                self.runtime.services.process_runner = self.process_runtime
            generic_attach = getattr(self.runtime.services, "start_services_with_attach", None)
            if callable(generic_attach):
                records = self._start_with_generic_attach(
                    descriptors=descriptors,
                    attach_parallel=attach_parallel,
                    on_service_retry=release_failed_port_then_report,
                    generic_attach=cast(Callable[..., dict[str, ServiceRecord]], generic_attach),
                )
            elif self.selected_service_types <= {"backend", "frontend"}:
                records = self._start_core_services_with_legacy_attach(
                    attach_parallel=attach_parallel,
                    on_service_retry=release_failed_port_then_report,
                )
            else:
                raise RuntimeError("Service manager does not support additional app services")
            self._record_port_lock_session(records.values())
            return records
        except Exception as exc:
            self._record_port_lock_session(dict(getattr(exc, "unterminated_services", {}) or {}).values())
            self._release_failed_start_reservations(exc)
            raise

    def _record_port_lock_session(self, services: Iterable[object]) -> None:
        raw_session_id = getattr(self.port_allocator, "session_id", None)
        session_id = raw_session_id.strip() if isinstance(raw_session_id, str) else ""
        if not session_id:
            return
        for service in services:
            if isinstance(service, ServiceRecord):
                service.port_lock_session = session_id

    def reserve_next(self, port: int) -> int:
        return self.port_allocator.reserve_next(port, owner=f"{self.project_name}:services")

    def _release_failed_service_port(self, service_type: str, port: int) -> None:
        release = getattr(self.port_allocator, "release", None)
        if not callable(release):
            return
        for owner in (
            f"{self.project_name}:{service_type}",
            f"{self.project_name}:services",
            f"{self.project_name}:services:{service_type}-launch",
        ):
            release(port, owner=owner)

    def _release_rebound_launch_port(self, service_type: str) -> None:
        port = self._rebound_launch_ports.pop(service_type, None)
        if port is None:
            return
        release = getattr(self.port_allocator, "release", None)
        if callable(release):
            release(port, owner=f"{self.project_name}:services:{service_type}-launch")

    def _release_failed_start_reservations(self, error: BaseException) -> None:
        preserved_service_types = {
            str(getattr(service, "type", "") or "").strip().lower()
            for service in dict(getattr(error, "unterminated_services", {}) or {}).values()
            if _service_has_recorded_pid(service)
        }
        for service_type, port in tuple(self._active_service_ports.items()):
            if service_type in preserved_service_types:
                continue
            self._release_failed_service_port(service_type, port)
            self._active_service_ports.pop(service_type, None)
            self._release_rebound_launch_port(service_type)

    def _start_with_generic_attach(
        self,
        *,
        descriptors: list[ServiceStartDescriptor],
        attach_parallel: bool,
        on_service_retry: Callable[[str, int, int, int, str | None], None],
        generic_attach: Callable[..., dict[str, ServiceRecord]],
    ) -> dict[str, ServiceRecord]:
        descriptor_by_type = {descriptor.service_type: descriptor for descriptor in descriptors}
        records: dict[str, ServiceRecord] = {}
        try:
            for layer in ordered_service_layers(
                tuple(descriptor.service_type for descriptor in descriptors),
                self.additional_services,
            ):
                layer_records = generic_attach(
                    project=self.project_name,
                    descriptors=tuple(descriptor_by_type[name] for name in layer),
                    reserve_next=self.reserve_next,
                    on_retry=on_service_retry,
                    parallel_start=attach_parallel and len(layer) > 1,
                )
                records.update(layer_records)
        except Exception as exc:
            unterminated = dict(getattr(exc, "unterminated_services", {}) or {})
            terminator = getattr(self.runtime, "_terminate_started_services", None)
            if records:
                if callable(terminator):
                    try:
                        failed_names = unconfirmed_service_names(
                            terminator(records),
                            records,
                        )
                    except Exception as cleanup_exc:  # noqa: BLE001
                        failed_names = set(records)
                        exc = RuntimeError(f"{exc}; cleanup error: {cleanup_exc}")
                else:
                    failed_names = set(records)
                unterminated.update((name, service) for name, service in records.items() if name in failed_names)
            if unterminated:
                names = ", ".join(sorted(unterminated))
                raise ServiceCleanupError(
                    f"{exc}; cleanup could not confirm exit for: {names}",
                    unterminated,
                ) from exc
            raise
        return records

    def _start_core_services_with_legacy_attach(
        self,
        *,
        attach_parallel: bool,
        on_service_retry: Callable[[str, int, int, int, str | None], None],
    ) -> dict[str, ServiceRecord]:
        return self.runtime.services.start_project_with_attach(
            project=self.project_name,
            backend_port=self.backend_plan.final,
            frontend_port=self.frontend_plan.final,
            backend_cwd=str(self.backend_cwd),
            frontend_cwd=str(self.frontend_cwd),
            start_backend=self.start_backend,
            start_frontend=self.start_frontend,
            reserve_next=self.reserve_next,
            detect_backend_actual=self.detect_backend_actual,
            detect_frontend_actual=self.detect_frontend_actual,
            backend_listener_expected=self.backend_listener_expected,
            frontend_listener_expected=True,
            on_retry=on_service_retry,
            parallel_start=attach_parallel,
        )

    def _service_descriptors(self) -> list[ServiceStartDescriptor]:
        descriptors: list[ServiceStartDescriptor] = []
        if "backend" in self.selected_service_types:
            descriptors.append(
                ServiceStartDescriptor(
                    service_type="backend",
                    cwd=str(self.backend_cwd),
                    requested_port=self.backend_plan.final,
                    start=self.start_backend,
                    detect_actual=self.detect_backend_actual,
                    listener_expected=self.backend_listener_expected,
                    log_path=self.backend_log_path,
                )
            )
        if "frontend" in self.selected_service_types:
            descriptors.append(
                ServiceStartDescriptor(
                    service_type="frontend",
                    cwd=str(self.frontend_cwd),
                    requested_port=self.frontend_plan.final,
                    start=self.start_frontend,
                    detect_actual=self.detect_frontend_actual,
                    listener_expected=True,
                    log_path=self.frontend_log_path,
                )
            )
        for service in sorted(self.additional_services, key=lambda item: (item.start_order, item.name)):
            launch = self.prepared_launches[service.name]
            descriptors.append(
                ServiceStartDescriptor(
                    service_type=service.name,
                    cwd=str(launch.cwd),
                    requested_port=launch.requested_port,
                    start=lambda port, service_name=service.name: self.start_additional_service(service_name, port),
                    detect_actual=lambda pid, requested, service_name=service.name: self.detect_additional_actual(
                        service_name, pid, requested
                    ),
                    listener_expected=service.expect_listener,
                    critical=service.critical,
                    log_path=launch.log_path,
                    public_url=launch.env.get(f"ENVCTL_SOURCE_SERVICE_{service.env_suffix}_PUBLIC_URL"),
                    health_url=launch.env.get(f"ENVCTL_SOURCE_SERVICE_{service.env_suffix}_HEALTH_URL"),
                )
            )
        return descriptors

    def _start_process(
        self,
        command: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        log_path: Path | str,
    ) -> object:
        start_background = getattr(self.process_runtime, "start_background", None)
        if callable(start_background):
            return start_background(
                command,
                cwd=cwd,
                env=env,
                stdout_path=log_path,
                stderr_path=log_path,
            )
        return self.process_runtime.start(
            command,
            cwd=cwd,
            env=env,
            stdout_path=log_path,
            stderr_path=log_path,
        )

    def _conflicting_start_result(self, service_name: str, port: int) -> tuple[bool, str | None, int | None] | None:
        remaining = self.runtime._conflict_remaining.get(service_name, 0)
        if remaining <= 0:
            return None
        self.runtime._conflict_remaining[service_name] = remaining - 1
        self.runtime._emit("service.start", project=self.project_name, service=service_name, port=port, retry=True)
        return False, "bind: address already in use", None

    def _launch_prepared_process(
        self,
        *,
        service_name: str,
        command: list[str],
        launch: PreparedServiceLaunch,
        launch_port: int,
        event_port: int,
        env_extra: dict[str, str],
    ) -> tuple[bool, str | None, int | None]:
        launch_started = time.monotonic()
        try:
            process = self._start_process(
                command,
                cwd=str(launch.cwd),
                env=self.command_env_builder(port=launch_port, extra=env_extra),
                log_path=launch.log_path,
            )
        except OSError as exc:
            detail = f"process spawn failed for {command[0]}: {exc}"
            self.runtime._emit(
                "service.failure",
                project=self.project_name,
                service=service_name,
                failure_class=ServiceFailureReason.PROCESS_SPAWN_FAILED.value,
                requested_port=event_port,
                detail=detail,
            )
            return False, detail, None
        pid = getattr(process, "pid", None)
        try:
            self._emit_attach_phase(service_name, "process_launch", launch_started)
            self.runtime._emit(
                "service.start",
                project=self.project_name,
                service=service_name,
                port=event_port,
                retry=False,
            )
        except Exception:  # noqa: BLE001
            pass
        return True, None, pid if isinstance(pid, int) and pid > 0 else None

    def start_backend(self, port: int) -> tuple[bool, str | None, int | None]:
        conflict_result = self._conflicting_start_result("backend", port)
        if conflict_result is not None:
            return conflict_result
        command_resolve_started = time.monotonic()
        command, _resolved_source = self.runtime._service_start_command_resolved(
            service_name="backend",
            project_root=self.project_root,
            port=port,
        )
        self._emit_attach_phase("backend", "command_resolution", command_resolve_started)
        return self._launch_prepared_process(
            service_name="backend",
            command=command,
            launch=self.prepared_launches["backend"],
            launch_port=port,
            event_port=port,
            env_extra=self.backend_env_extra,
        )

    def start_frontend(self, port: int) -> tuple[bool, str | None, int | None]:
        conflict_result = self._conflicting_start_result("frontend", port)
        if conflict_result is not None:
            return conflict_result
        launch_port = port + self.rebound_delta if self.rebound_delta > 0 else port
        if self.rebound_delta > 0:
            launch_port = self.port_allocator.reserve_next(
                launch_port,
                owner=f"{self.project_name}:services:frontend-launch",
            )
            self._rebound_launch_ports["frontend"] = launch_port
        try:
            command_resolve_started = time.monotonic()
            command, _resolved_source = self.runtime._service_start_command_resolved(
                service_name="frontend",
                project_root=self.project_root,
                port=launch_port,
            )
            self._emit_attach_phase("frontend", "command_resolution", command_resolve_started)
            result = self._launch_prepared_process(
                service_name="frontend",
                command=command,
                launch=self.prepared_launches["frontend"],
                launch_port=launch_port,
                event_port=port,
                env_extra=self.frontend_env_extra,
            )
        except Exception:
            self._release_rebound_launch_port("frontend")
            raise
        if not isinstance(result[2], int) or isinstance(result[2], bool) or result[2] <= 0:
            self._release_rebound_launch_port("frontend")
        return result

    def start_additional_service(self, service_name: str, port: int) -> tuple[bool, str | None, int | None]:
        conflict_result = self._conflicting_start_result(service_name, port)
        if conflict_result is not None:
            return conflict_result
        launch = self.prepared_launches[service_name]
        service = self.runtime.config.app_service_by_name(service_name)
        if service is None:
            return False, f"unknown additional service {service_name}", None
        command_resolve_started = time.monotonic()
        command = self.runtime._split_command(
            service.start_cmd,
            port=port,
            replacements={
                "project_root": str(self.project_root),
                "service_dir": str(launch.cwd),
                "service_name": service_name,
            },
            cwd=launch.cwd,
        )
        self._emit_attach_phase(service_name, "command_resolution", command_resolve_started)
        return self._launch_prepared_process(
            service_name=service_name,
            command=command,
            launch=launch,
            launch_port=port,
            event_port=port,
            env_extra=launch.env,
        )

    def detect_backend_actual(self, pid: int | None, requested: int) -> int | None:
        if not self.backend_listener_expected:
            self.runtime._emit(
                "service.bind.skipped",
                project=self.project_name,
                service="backend",
                reason="listener_not_expected",
            )
            return None
        self.runtime._emit(
            "service.bind.requested",
            project=self.project_name,
            service="backend",
            requested_port=requested,
        )
        detect_started = time.monotonic()
        actual_override = self._actual_port_override("ENVCTL_TEST_BACKEND_ACTUAL_PORT")
        if actual_override > 0:
            actual = actual_override
        else:
            detected = self.runtime._detect_service_actual_port(
                pid=pid,
                requested_port=requested,
                service_name="backend",
                log_path=self.backend_log_path,
            )
            actual = self._resolve_detected_actual(
                service_name="backend",
                detected=detected,
                requested=requested,
                log_path=self.backend_log_path,
                pid=pid,
                fallback_actual=requested,
                failure_port=requested,
            )
        self.runtime._emit("service.bind.actual", project=self.project_name, service="backend", actual_port=actual)
        self._emit_attach_phase("backend", "actual_port_detection", detect_started)
        return actual

    def detect_frontend_actual(self, pid: int | None, requested: int) -> int | None:
        self.runtime._emit(
            "service.bind.requested",
            project=self.project_name,
            service="frontend",
            requested_port=requested,
        )
        detect_started = time.monotonic()
        actual_override = self._actual_port_override("ENVCTL_TEST_FRONTEND_ACTUAL_PORT")
        if actual_override > 0:
            actual = actual_override
        else:
            probe_port = requested + self.rebound_delta if self.rebound_delta > 0 else requested
            detected = self.runtime._detect_service_actual_port(
                pid=pid,
                requested_port=probe_port,
                service_name="frontend",
                log_path=self.frontend_log_path,
            )
            if detected is None and probe_port != requested:
                detected = self.runtime._detect_service_actual_port(
                    pid=pid,
                    requested_port=requested,
                    service_name="frontend",
                    log_path=self.frontend_log_path,
                )
            actual = self._resolve_detected_actual(
                service_name="frontend",
                detected=detected,
                requested=requested,
                log_path=self.frontend_log_path,
                pid=pid,
                fallback_actual=probe_port,
                failure_port=probe_port,
            )
        self.runtime._emit("service.bind.actual", project=self.project_name, service="frontend", actual_port=actual)
        self._emit_attach_phase("frontend", "actual_port_detection", detect_started)
        return actual

    def detect_additional_actual(self, service_name: str, pid: int | None, requested: int) -> int | None:
        launch = self.prepared_launches[service_name]
        if not launch.listener_expected:
            self.runtime._emit(
                "service.bind.skipped",
                project=self.project_name,
                service=service_name,
                reason="listener_not_expected",
            )
            return None
        self.runtime._emit(
            "service.bind.requested",
            project=self.project_name,
            service=service_name,
            requested_port=requested,
        )
        detect_started = time.monotonic()
        detected = self.runtime._detect_service_actual_port(
            pid=pid,
            requested_port=requested,
            service_name=service_name,
            log_path=launch.log_path,
        )
        actual = self._resolve_detected_actual(
            service_name=service_name,
            detected=detected,
            requested=requested,
            log_path=launch.log_path,
            pid=pid,
            fallback_actual=requested,
            failure_port=requested,
        )
        self.runtime._emit(
            "service.bind.actual",
            project=self.project_name,
            service=service_name,
            actual_port=actual,
        )
        self._emit_attach_phase(service_name, "actual_port_detection", detect_started)
        return actual

    def _resolve_detected_actual(
        self,
        *,
        service_name: str,
        detected: int | None,
        requested: int,
        log_path: str,
        pid: int | None,
        fallback_actual: int,
        failure_port: int,
    ) -> int:
        if detected is not None:
            if detected != requested:
                self.runtime._emit("port.rebound", project=self.project_name, service=service_name, port=detected)
            return detected
        if self.runtime._listener_truth_enforced():
            detail = self.runtime._service_listener_failure_detail(log_path=log_path, pid=pid)
            error_suffix = f" ({detail})" if detail else ""
            failure_class = service_listener_failure_class(detail)
            self.runtime._emit(
                "service.failure",
                project=self.project_name,
                service=service_name,
                failure_class=failure_class,
                requested_port=requested,
                detail=detail,
            )
            if failure_class == ServiceFailureReason.DEPENDENCY_MISSING.value:
                failure_summary = f"{service_name} is missing a required executable or module"
            elif failure_class == ServiceFailureReason.PROCESS_EXITED.value:
                failure_summary = f"{service_name} process exited before opening its listener"
            else:
                failure_summary = f"{service_name} listener not detected"
            raise RuntimeError(f"{failure_summary} for {self.project_name} on port {failure_port}{error_suffix}")
        self.runtime._emit(
            "service.failure",
            project=self.project_name,
            service=service_name,
            failure_class="listener_unverified",
            requested_port=requested,
        )
        return fallback_actual

    def _actual_port_override(self, key: str) -> int:
        raw = str(getattr(self.runtime, "env", {}).get(key, "") or "").strip()
        try:
            return int(raw)
        except ValueError:
            return 0

    def _emit_attach_phase(self, service_name: str, phase: str, started: float) -> None:
        self.runtime._emit(
            "service.attach.phase",
            project=self.project_name,
            service=service_name,
            phase=phase,
            duration_ms=round((time.monotonic() - started) * 1000.0, 2),
        )


def _service_has_recorded_pid(service: object) -> bool:
    listener_pids = getattr(service, "listener_pids", None)
    listeners = listener_pids if isinstance(listener_pids, (list, tuple, set, frozenset)) else ()
    candidates = [getattr(service, "pid", None), *listeners]
    return any(isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 for pid in candidates)
