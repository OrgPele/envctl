from __future__ import annotations

import concurrent.futures
import os
import signal
import time
from dataclasses import dataclass
from typing import Callable

from envctl_engine.state.models import ServiceRecord
from envctl_engine.requirements.common import is_bind_conflict


class ServiceStartError(RuntimeError):
    """Raised when a service fails to start after retry policy."""


@dataclass(slots=True)
class ServiceStartOutcome:
    record: ServiceRecord
    retries: int


@dataclass(slots=True)
class ServiceStartDescriptor:
    service_type: str
    cwd: str
    requested_port: int
    start: Callable[[int], tuple[bool, str | None, int | None]]
    detect_actual: Callable[[int | None, int], int | None] | None = None
    listener_expected: bool = True
    max_retries: int = 3


class ServiceManager:
    def start_service_with_retry(
        self,
        *,
        project: str,
        service_type: str,
        cwd: str,
        requested_port: int,
        start: Callable[[int], tuple[bool, str | None, int | None]],
        reserve_next: Callable[[int], int],
        detect_actual: Callable[[int | None, int], int | None] | None = None,
        listener_expected: bool = True,
        max_retries: int = 3,
        on_retry: Callable[[str, int, int, int, str | None], None] | None = None,
    ) -> ServiceRecord:
        current_port = requested_port
        retries = 0

        while True:
            success, error, pid = start(current_port)
            if success:
                try:
                    actual_port: int | None = current_port if listener_expected else None
                    if detect_actual is not None:
                        actual_port = detect_actual(pid, current_port)
                    return ServiceRecord(
                        name=f"{project} {_service_display_name(service_type)}",
                        type=service_type,
                        cwd=cwd,
                        pid=pid,
                        requested_port=requested_port if listener_expected else None,
                        actual_port=actual_port,
                        status="running",
                        started_at=time.time(),
                        listener_expected=listener_expected,
                    )
                except RuntimeError as exc:
                    error = str(exc)
                    _terminate_pid(pid, process_runner=self)

            if retries >= max_retries or not _is_retryable_error(error):
                raise ServiceStartError(
                    f"Failed to start {project} {service_type} on port {current_port}: {error or 'unknown'}"
                )

            retries += 1
            next_port = reserve_next(current_port + 1)
            if on_retry is not None:
                on_retry(service_type, current_port, next_port, retries, error)
            current_port = next_port

    def start_project_with_attach(
        self,
        *,
        project: str,
        backend_port: int,
        frontend_port: int,
        backend_cwd: str,
        frontend_cwd: str,
        start_backend: Callable[[int], tuple[bool, str | None, int | None]],
        start_frontend: Callable[[int], tuple[bool, str | None, int | None]],
        reserve_next: Callable[[int], int],
        detect_backend_actual: Callable[[int | None, int], int] | None = None,
        detect_frontend_actual: Callable[[int | None, int], int] | None = None,
        backend_listener_expected: bool = True,
        frontend_listener_expected: bool = True,
        max_retries: int = 3,
        on_retry: Callable[[str, int, int, int, str | None], None] | None = None,
        parallel_start: bool = False,
    ) -> dict[str, ServiceRecord]:
        return self.start_services_with_attach(
            project=project,
            descriptors=(
                ServiceStartDescriptor(
                    service_type="backend",
                    cwd=backend_cwd,
                    requested_port=backend_port,
                    start=start_backend,
                    detect_actual=detect_backend_actual,
                    listener_expected=backend_listener_expected,
                    max_retries=max_retries,
                ),
                ServiceStartDescriptor(
                    service_type="frontend",
                    cwd=frontend_cwd,
                    requested_port=frontend_port,
                    start=start_frontend,
                    detect_actual=detect_frontend_actual,
                    listener_expected=frontend_listener_expected,
                    max_retries=max_retries,
                ),
            ),
            reserve_next=reserve_next,
            on_retry=on_retry,
            parallel_start=parallel_start,
            max_workers=2,
        )

    def start_services_with_attach(
        self,
        *,
        project: str,
        descriptors: tuple[ServiceStartDescriptor, ...],
        reserve_next: Callable[[int], int],
        on_retry: Callable[[str, int, int, int, str | None], None] | None = None,
        parallel_start: bool = False,
        max_workers: int | None = None,
    ) -> dict[str, ServiceRecord]:
        def start_record(descriptor: ServiceStartDescriptor) -> ServiceRecord:
            return self.start_service_with_retry(
                project=project,
                service_type=descriptor.service_type,
                cwd=descriptor.cwd,
                requested_port=descriptor.requested_port,
                start=descriptor.start,
                reserve_next=reserve_next,
                detect_actual=descriptor.detect_actual,
                listener_expected=descriptor.listener_expected,
                max_retries=descriptor.max_retries,
                on_retry=on_retry,
            )

        partial_records: list[ServiceRecord] = []
        try:
            if parallel_start and len(descriptors) > 1:
                worker_count = max_workers or len(descriptors)
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(descriptors), worker_count)) as executor:
                    future_map = {executor.submit(start_record, descriptor): descriptor for descriptor in descriptors}
                    for future in concurrent.futures.as_completed(future_map):
                        partial_records.append(future.result())
            else:
                for descriptor in descriptors:
                    partial_records.append(start_record(descriptor))
        except Exception:
            for record in partial_records:
                _terminate_pid(record.pid, process_runner=self)
            raise
        return {record.name: record for record in partial_records}


def _is_retryable_error(error: str | None) -> bool:
    if is_bind_conflict(error):
        return True
    normalized = (error or "").strip().lower()
    if "listener not detected" in normalized:
        return True
    if "address already in use" in normalized:
        return True
    return False


def _service_display_name(service_type: str) -> str:
    return " ".join(part.capitalize() for part in str(service_type).replace("_", "-").split("-") if part)


def _terminate_pid(pid: int | None, *, process_runner: object | None = None) -> None:
    if not isinstance(pid, int) or pid <= 0:
        return
    terminator = getattr(process_runner, "terminate_process_group", None) if process_runner is not None else None
    if callable(terminator):
        try:
            terminator(pid, term_timeout=2.0, kill_timeout=1.0)
            return
        except Exception:  # noqa: BLE001
            pass
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
