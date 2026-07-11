from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import os
from pathlib import Path
import time
from typing import Any, cast

from envctl_engine.runtime.service_manager import ServiceStartDescriptor
from envctl_engine.runtime.docker_service_runtime import (
    DockerServiceLaunch,
    DockerServiceRuntime,
    docker_service_container_command_source,
    docker_service_mode_enabled,
)
from envctl_engine.startup.service_execution_policy import ordered_service_layers
from envctl_engine.startup.service_execution_records import PreparedServiceLaunch
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
    docker_mode: bool = False
    refresh_cache: bool = False
    _container_launches: dict[str, DockerServiceLaunch] = field(default_factory=dict, init=False)

    def start(
        self,
        *,
        attach_parallel: bool,
        on_service_retry: Callable[[str, int, int, int, str | None], None],
    ) -> dict[str, ServiceRecord]:
        descriptors = self._service_descriptors()
        try:
            generic_attach = getattr(self.runtime.services, "start_services_with_attach", None)
            if callable(generic_attach):
                records = self._start_with_generic_attach(
                    descriptors=descriptors,
                    attach_parallel=attach_parallel,
                    on_service_retry=on_service_retry,
                    generic_attach=cast(Callable[..., dict[str, ServiceRecord]], generic_attach),
                )
            elif self.selected_service_types <= {"backend", "frontend"}:
                records = self._start_core_services_with_legacy_attach(
                    attach_parallel=attach_parallel,
                    on_service_retry=on_service_retry,
                )
            else:
                raise RuntimeError("Service manager does not support additional app services")
        except Exception:
            self._cleanup_container_launches()
            raise
        self._annotate_container_records(records)
        return records

    def reserve_next(self, port: int) -> int:
        return self.port_allocator.reserve_next(port, owner=f"{self.project_name}:services")

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
                    start=lambda port, service_name=service.name: self.start_additional_service(
                        service_name, port
                    ),
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
        pid_fallback: int,
    ) -> tuple[bool, str | None, int | None]:
        launch_started = time.monotonic()
        service_env = self.command_env_builder(port=launch_port, extra=env_extra)
        if self.docker_mode or docker_service_mode_enabled(self.runtime):
            try:
                container_launch = DockerServiceRuntime(
                    self.runtime,
                    self.process_runtime,
                    refresh_cache=self.refresh_cache,
                ).launch(
                    project_name=self.project_name,
                    project_root=self.project_root,
                    service_name=service_name,
                    cwd=launch.cwd,
                    command=command,
                    env=service_env,
                    host_port=event_port,
                    container_port=launch_port,
                    listener_expected=launch.listener_expected,
                    log_path=launch.log_path,
                )
            except RuntimeError as exc:
                self._emit_attach_phase(service_name, "container_launch", launch_started)
                return False, str(exc), None
            self._container_launches[service_name] = container_launch
            process_pid = None
            phase = "container_launch"
        else:
            process = self._start_process(
                command,
                cwd=str(launch.cwd),
                env=service_env,
                log_path=launch.log_path,
            )
            process_pid = getattr(process, "pid", pid_fallback)
            phase = "process_launch"
        self._emit_attach_phase(service_name, phase, launch_started)
        self.runtime._emit(
            "service.start",
            project=self.project_name,
            service=service_name,
            port=event_port,
            retry=False,
        )
        return True, None, process_pid

    def _container_actual_port(
        self,
        service_name: str,
        requested: int,
        *,
        listener_expected: bool = True,
    ) -> int | None:
        launch = self._container_launches.get(service_name)
        if launch is None:
            return None
        ready = DockerServiceRuntime(self.runtime, self.process_runtime).wait_until_ready(
            launch,
            port=requested,
            listener_expected=listener_expected,
        )
        if ready:
            return requested if listener_expected else None
        detail = f"container {launch.container_name} exited or did not become ready"
        cleanup_detail = self._remove_failed_container_launch(service_name, launch)
        if cleanup_detail:
            detail = f"{detail}; {cleanup_detail}"
        self.runtime._emit(
            "service.failure",
            project=self.project_name,
            service=service_name,
            failure_class="container_not_ready",
            requested_port=requested if listener_expected else None,
            detail=detail,
        )
        raise RuntimeError(detail)

    def _remove_failed_container_launch(
        self,
        service_name: str,
        launch: DockerServiceLaunch,
    ) -> str | None:
        try:
            removed = DockerServiceRuntime(self.runtime, self.process_runtime).stop(launch.container_id)
        except Exception as exc:  # noqa: BLE001 - preserve the launch in state for a later stop retry
            return f"failed to remove container: {exc}"
        if not removed:
            return "failed to remove container"
        if self._container_launches.get(service_name) == launch:
            self._container_launches.pop(service_name, None)
        return None

    def _annotate_container_records(self, records: dict[str, ServiceRecord]) -> None:
        for record in records.values():
            service_name = str(record.service_slug or record.type)
            launch = self._container_launches.get(service_name)
            if launch is None:
                continue
            record.runtime_kind = "docker"
            record.container_id = launch.container_id
            record.container_name = launch.container_name
            record.container_image = launch.image

    def _cleanup_container_launches(self) -> None:
        docker_runtime = DockerServiceRuntime(self.runtime, self.process_runtime)
        for launch in tuple(self._container_launches.values()):
            docker_runtime.stop(launch.container_id)
        self._container_launches.clear()

    def start_backend(self, port: int) -> tuple[bool, str | None, int | None]:
        conflict_result = self._conflicting_start_result("backend", port)
        if conflict_result is not None:
            return conflict_result
        command_resolve_started = time.monotonic()
        command = self._core_service_command("backend", port)
        self._emit_attach_phase("backend", "command_resolution", command_resolve_started)
        return self._launch_prepared_process(
            service_name="backend",
            command=command,
            launch=self.prepared_launches["backend"],
            launch_port=port,
            event_port=port,
            env_extra=self.backend_env_extra,
            pid_fallback=os.getpid(),
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
        command_resolve_started = time.monotonic()
        command = self._core_service_command("frontend", launch_port)
        self._emit_attach_phase("frontend", "command_resolution", command_resolve_started)
        return self._launch_prepared_process(
            service_name="frontend",
            command=command,
            launch=self.prepared_launches["frontend"],
            launch_port=launch_port,
            event_port=port,
            env_extra=self.frontend_env_extra,
            pid_fallback=os.getpid() + 1,
        )

    def _core_service_command(self, service_name: str, port: int) -> list[str]:
        container_command_source = docker_service_container_command_source(
            self.runtime,
            service_name,
            docker_mode=self.docker_mode or docker_service_mode_enabled(self.runtime),
        )
        if container_command_source is not None:
            return []
        command, _resolved_source = self.runtime._service_start_command_resolved(
            service_name=service_name,
            project_root=self.project_root,
            port=port,
        )
        return command

    def start_additional_service(self, service_name: str, port: int) -> tuple[bool, str | None, int | None]:
        conflict_result = self._conflicting_start_result(service_name, port)
        if conflict_result is not None:
            return conflict_result
        launch = self.prepared_launches[service_name]
        service = self.runtime.config.app_service_by_name(service_name)
        if service is None:
            return False, f"unknown additional service {service_name}", None
        command_resolve_started = time.monotonic()
        if docker_service_container_command_source(
            self.runtime,
            service_name,
            docker_mode=self.docker_mode or docker_service_mode_enabled(self.runtime),
        ) is not None:
            command = []
        else:
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
            pid_fallback=os.getpid(),
        )

    def detect_backend_actual(self, pid: int | None, requested: int) -> int | None:
        if "backend" in self._container_launches:
            return self._container_actual_port(
                "backend",
                requested,
                listener_expected=self.backend_listener_expected,
            )
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
        container_actual = self._container_actual_port("frontend", requested)
        if "frontend" in self._container_launches:
            return container_actual
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
        if service_name in self._container_launches:
            return self._container_actual_port(
                service_name,
                requested,
                listener_expected=launch.listener_expected,
            )
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
            self.runtime._emit(
                "service.failure",
                project=self.project_name,
                service=service_name,
                failure_class="listener_not_detected",
                requested_port=requested,
                detail=detail,
            )
            raise RuntimeError(
                f"{service_name} listener not detected for {self.project_name} on port {failure_port}{error_suffix}"
            )
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
