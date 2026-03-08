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
        detect_actual: Callable[[int | None, int], int] | None = None,
        max_retries: int = 3,
        on_retry: Callable[[str, int, int, int, str | None], None] | None = None,
    ) -> ServiceRecord:
        current_port = requested_port
        retries = 0

        while True:
            success, error, pid = start(current_port)
            if success:
                try:
                    actual_port = current_port
                    if detect_actual is not None:
                        actual_port = detect_actual(pid, current_port)
                    return ServiceRecord(
                        name=f"{project} {service_type.title()}",
                        type=service_type,
                        cwd=cwd,
                        pid=pid,
                        requested_port=requested_port,
                        actual_port=actual_port,
                        status="running",
                        started_at=time.time(),
                    )
                except RuntimeError as exc:
                    error = str(exc)
                    _terminate_pid(pid)

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
        max_retries: int = 3,
        on_retry: Callable[[str, int, int, int, str | None], None] | None = None,
        parallel_start: bool = False,
    ) -> dict[str, ServiceRecord]:
        def start_backend_record() -> ServiceRecord:
            return self.start_service_with_retry(
                project=project,
                service_type="backend",
                cwd=backend_cwd,
                requested_port=backend_port,
                start=start_backend,
                reserve_next=reserve_next,
                detect_actual=detect_backend_actual,
                max_retries=max_retries,
                on_retry=on_retry,
            )

        def start_frontend_record() -> ServiceRecord:
            return self.start_service_with_retry(
                project=project,
                service_type="frontend",
                cwd=frontend_cwd,
                requested_port=frontend_port,
                start=start_frontend,
                reserve_next=reserve_next,
                detect_actual=detect_frontend_actual,
                max_retries=max_retries,
                on_retry=on_retry,
            )

        if parallel_start:
            partial_records: list[ServiceRecord] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                backend_future = executor.submit(start_backend_record)
                frontend_future = executor.submit(start_frontend_record)
                try:
                    backend = backend_future.result()
                    partial_records.append(backend)
                    frontend = frontend_future.result()
                    partial_records.append(frontend)
                except Exception:
                    for record in partial_records:
                        _terminate_pid(record.pid)
                    raise
        else:
            backend = start_backend_record()
            frontend = start_frontend_record()

        return {
            backend.name: backend,
            frontend.name: frontend,
        }


def _is_retryable_error(error: str | None) -> bool:
    if is_bind_conflict(error):
        return True
    normalized = (error or "").strip().lower()
    if "listener not detected" in normalized:
        return True
    if "address already in use" in normalized:
        return True
    return False


def _terminate_pid(pid: int | None) -> None:
    if not isinstance(pid, int) or pid <= 0:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
