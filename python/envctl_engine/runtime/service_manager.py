from __future__ import annotations

import concurrent.futures
import os
import signal
import time
from dataclasses import dataclass
from collections.abc import Callable, Sequence

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
        detect_actual: Callable[[int | None, int], int | None] | None = None,
        listener_expected: bool = True,
        public_url: str | None = None,
        health_url: str | None = None,
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
                        name=f"{project} {_display_service_type(service_type)}",
                        type=service_type,
                        cwd=cwd,
                        pid=pid,
                        requested_port=requested_port if listener_expected else None,
                        actual_port=actual_port,
                        status="running",
                        started_at=time.time(),
                        listener_expected=listener_expected,
                        public_url=public_url,
                        health_url=health_url,
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
        descriptors = (
            ServiceAttachDescriptor(
                service_type="backend",
                cwd=backend_cwd,
                requested_port=backend_port,
                start=start_backend,
                detect_actual=detect_backend_actual,
                listener_expected=backend_listener_expected,
            ),
            ServiceAttachDescriptor(
                service_type="frontend",
                cwd=frontend_cwd,
                requested_port=frontend_port,
                start=start_frontend,
                detect_actual=detect_frontend_actual,
                listener_expected=frontend_listener_expected,
            ),
        )
        return self.start_services_with_attach(
            project=project,
            descriptors=descriptors,
            reserve_next=reserve_next,
            max_retries=max_retries,
            on_retry=on_retry,
            parallel_start=parallel_start,
            max_workers=2,
        )

    def start_services_with_attach(
        self,
        *,
        project: str,
        descriptors: Sequence[ServiceAttachDescriptor],
        reserve_next: Callable[[int], int],
        max_retries: int = 3,
        on_retry: Callable[[str, int, int, int, str | None], None] | None = None,
        parallel_start: bool = False,
        max_workers: int | None = None,
    ) -> dict[str, ServiceRecord]:
        records: dict[str, ServiceRecord] = {}
        partial_records: list[ServiceRecord] = []

        def start_descriptor(descriptor: ServiceAttachDescriptor) -> ServiceRecord:
            service_type = descriptor.service_type
            start = descriptor.start
            detect_actual = descriptor.detect_actual
            public_url = str(getattr(descriptor, "public_url", "") or "").strip() or None
            health_url = str(getattr(descriptor, "health_url", "") or "").strip() or None
            return self.start_service_with_retry(
                project=project,
                service_type=service_type,
                cwd=descriptor.cwd,
                requested_port=descriptor.requested_port,
                start=start,
                reserve_next=reserve_next,
                detect_actual=detect_actual,
                listener_expected=descriptor.listener_expected,
                public_url=public_url,
                health_url=health_url,
                max_retries=max_retries,
                on_retry=on_retry,
            )

        try:
            if parallel_start and len(descriptors) > 1:
                workers = max_workers or len(descriptors)
                workers = max(1, min(workers, len(descriptors)))
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = [executor.submit(start_descriptor, descriptor) for descriptor in descriptors]
                    concurrent.futures.wait(futures)
                    first_error: BaseException | None = None
                    for future in futures:
                        try:
                            record = future.result()
                        except BaseException as exc:  # noqa: BLE001
                            if first_error is None:
                                first_error = exc
                            continue
                        partial_records.append(record)
                        records[record.name] = record
                    if first_error is not None:
                        raise first_error
            else:
                for descriptor in descriptors:
                    record = start_descriptor(descriptor)
                    partial_records.append(record)
                    records[record.name] = record
        except Exception:
            for record in partial_records:
                _terminate_pid(record.pid, process_runner=self)
            raise
        return records


@dataclass(frozen=True, slots=True)
class ServiceAttachDescriptor:
    service_type: str
    cwd: str
    requested_port: int
    start: Callable[[int], tuple[bool, str | None, int | None]]
    detect_actual: Callable[[int | None, int], int | None] | None = None
    listener_expected: bool = True
    public_url: str | None = None
    health_url: str | None = None


def _is_retryable_error(error: str | None) -> bool:
    if is_bind_conflict(error):
        return True
    normalized = (error or "").strip().lower()
    if "listener not detected" in normalized:
        return True
    if "address already in use" in normalized:
        return True
    return False


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


def _display_service_type(service_type: str) -> str:
    return " ".join(part.capitalize() for part in str(service_type).strip().split("-") if part)
