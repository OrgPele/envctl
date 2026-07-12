from __future__ import annotations

import concurrent.futures
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Callable

from envctl_engine.requirements.common_contracts import is_bind_conflict
from envctl_engine.shared.process_termination import terminate_pid
from envctl_engine.shared.services import service_display_name
from envctl_engine.state.models import ServiceRecord


class ServiceStartError(RuntimeError):
    """Raised when a service fails to start after retry policy."""


class ServiceCleanupError(ServiceStartError):
    """Raised when a failed startup leaves processes whose exit is unconfirmed."""

    def __init__(self, message: str, unterminated_services: dict[str, ServiceRecord]) -> None:
        super().__init__(message)
        self.unterminated_services = dict(unterminated_services)


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
    critical: bool = True
    log_path: str | None = None
    public_url: str | None = None
    health_url: str | None = None
    pid_required: bool = True


class ServiceManager:
    def __init__(self, *, process_runner: object | None = None) -> None:
        self.process_runner = process_runner

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
        pid_required: bool = True,
        max_retries: int = 3,
        on_retry: Callable[[str, int, int, int, str | None], None] | None = None,
    ) -> ServiceRecord:
        current_port = requested_port
        retries = 0

        while True:
            success, error, pid = start(current_port)
            if success:
                valid_pid = isinstance(pid, int) and not isinstance(pid, bool) and pid > 0
                if pid_required and not valid_pid:
                    record = _failed_start_record(
                        project=project,
                        service_type=service_type,
                        cwd=cwd,
                        pid=None,
                        requested_port=current_port if listener_expected else None,
                        listener_expected=listener_expected,
                        failure_detail="service launcher reported success without a valid PID",
                    )
                    raise ServiceCleanupError(
                        f"Service launcher for {record.name} reported success without a valid PID",
                        {record.name: record},
                    )
                try:
                    actual_port: int | None = current_port if listener_expected else None
                    if detect_actual is not None:
                        actual_port = detect_actual(pid, current_port)
                    return ServiceRecord(
                        name=f"{project} {service_display_name(service_type)}",
                        type=service_type,
                        cwd=cwd,
                        pid=pid if valid_pid else None,
                        requested_port=requested_port if listener_expected else None,
                        actual_port=actual_port,
                        status="running",
                        started_at=time.time(),
                        listener_expected=listener_expected,
                    )
                except BaseException as exc:  # noqa: BLE001 - cancellation must not leak the launched PID
                    cleanup_confirmed = _terminate_pid_safely(
                        pid,
                        process_runner=self.process_runner,
                    )
                    if not cleanup_confirmed:
                        record = _failed_start_record(
                            project=project,
                            service_type=service_type,
                            cwd=cwd,
                            pid=pid,
                            requested_port=current_port if listener_expected else None,
                            listener_expected=listener_expected,
                            failure_detail=str(exc),
                        )
                        unterminated = {record.name: record}
                        if not isinstance(exc, Exception):
                            _retain_unterminated_services(exc, unterminated)
                            raise
                        raise ServiceCleanupError(
                            f"{exc}; cleanup could not confirm exit of PID {pid}",
                            unterminated,
                        ) from exc
                    if not isinstance(exc, Exception):
                        raise
                    error = str(exc)
            elif isinstance(pid, int) and pid > 0:
                if not _terminate_pid(pid, process_runner=self.process_runner):
                    record = _failed_start_record(
                        project=project,
                        service_type=service_type,
                        cwd=cwd,
                        pid=pid,
                        requested_port=current_port if listener_expected else None,
                        listener_expected=listener_expected,
                        failure_detail=error or "service launcher reported failure",
                    )
                    raise ServiceCleanupError(
                        f"{error or 'service launcher reported failure'}; cleanup could not confirm exit of PID {pid}",
                        {record.name: record},
                    )

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
            try:
                record = self.start_service_with_retry(
                    project=project,
                    service_type=descriptor.service_type,
                    cwd=descriptor.cwd,
                    requested_port=descriptor.requested_port,
                    start=descriptor.start,
                    reserve_next=reserve_next,
                    detect_actual=descriptor.detect_actual,
                    listener_expected=descriptor.listener_expected,
                    pid_required=descriptor.pid_required,
                    max_retries=descriptor.max_retries,
                    on_retry=on_retry,
                )
            except Exception as exc:
                if isinstance(exc, ServiceCleanupError):
                    raise
                if descriptor.critical:
                    raise
                record = ServiceRecord(
                    name=f"{project} {service_display_name(descriptor.service_type)}",
                    type=descriptor.service_type,
                    cwd=descriptor.cwd,
                    requested_port=descriptor.requested_port if descriptor.listener_expected else None,
                    actual_port=None,
                    status="degraded",
                    listener_expected=descriptor.listener_expected,
                    failure_detail=str(exc),
                    critical=False,
                    degraded=True,
                )
            record.project = project
            record.service_slug = descriptor.service_type
            record.log_path = descriptor.log_path or record.log_path
            record.public_url = descriptor.public_url or record.public_url
            record.health_url = descriptor.health_url or record.health_url
            record.critical = bool(descriptor.critical)
            record.degraded = bool(getattr(record, "degraded", False))
            return record

        partial_records: list[ServiceRecord] = []
        try:
            if parallel_start and len(descriptors) > 1:
                records_by_index, failures_by_index, interruption = _start_parallel_records(
                    descriptors=descriptors,
                    start_record=start_record,
                    max_workers=max_workers,
                )
                partial_records.extend(records_by_index[index] for index in sorted(records_by_index))
                primary_failure = _primary_parallel_failure(
                    failures_by_index,
                    interruption=interruption,
                )
                if primary_failure is not None:
                    unterminated = _unterminated_services_from_failures(failures_by_index.values())
                    if unterminated:
                        if not isinstance(primary_failure, Exception):
                            _retain_unterminated_services(primary_failure, unterminated)
                            raise primary_failure
                        raise ServiceCleanupError(str(primary_failure), unterminated) from primary_failure
                    raise primary_failure
            else:
                for descriptor in descriptors:
                    partial_records.append(start_record(descriptor))
        except BaseException as exc:  # noqa: BLE001 - cancellation still requires transactional rollback
            unterminated = _unterminated_services_from_failures((exc,))
            unterminated.update(
                _cleanup_service_records(
                    partial_records,
                    process_runner=self.process_runner,
                )
            )
            if unterminated:
                if not isinstance(exc, Exception):
                    _retain_unterminated_services(exc, unterminated)
                    raise
                names = ", ".join(sorted(unterminated))
                raise ServiceCleanupError(
                    f"{exc}; cleanup could not confirm exit for: {names}",
                    unterminated,
                ) from exc
            raise
        return {record.name: record for record in partial_records}


def _is_retryable_error(error: str | None) -> bool:
    if is_bind_conflict(error):
        return True
    normalized = (error or "").strip().lower()
    if "address already in use" in normalized:
        return True
    return False


def _terminate_pid(pid: int | None, *, process_runner: object | None = None) -> bool:
    return terminate_pid(
        pid,
        process_runner=process_runner,
        term_timeout=2.0,
        kill_timeout=1.0,
    )


def _terminate_pid_safely(pid: int | None, *, process_runner: object | None = None) -> bool:
    try:
        return _terminate_pid(pid, process_runner=process_runner)
    except BaseException:  # noqa: BLE001 - cleanup must not mask the triggering cancellation
        return False


def _cleanup_service_records(
    records: Iterable[ServiceRecord],
    *,
    process_runner: object | None,
) -> dict[str, ServiceRecord]:
    unterminated: dict[str, ServiceRecord] = {}
    for record in records:
        if not _terminate_pid_safely(record.pid, process_runner=process_runner):
            unterminated[record.name] = record
    return unterminated


def _retain_unterminated_services(
    failure: BaseException,
    services: dict[str, ServiceRecord],
) -> None:
    retained = _unterminated_services_from_failures((failure,))
    retained.update(services)
    try:
        failure.unterminated_services = retained  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - built-in cancellation types normally allow metadata
        failure.add_note("cleanup could not confirm exit for: " + ", ".join(sorted(retained)))


def _start_parallel_records(
    *,
    descriptors: tuple[ServiceStartDescriptor, ...],
    start_record: Callable[[ServiceStartDescriptor], ServiceRecord],
    max_workers: int | None,
) -> tuple[dict[int, ServiceRecord], dict[int, BaseException], BaseException | None]:
    records_by_index: dict[int, ServiceRecord] = {}
    failures_by_index: dict[int, BaseException] = {}
    future_map: dict[concurrent.futures.Future[ServiceRecord], int] = {}
    collected: set[concurrent.futures.Future[ServiceRecord]] = set()
    interruption: BaseException | None = None
    worker_count = max_workers or len(descriptors)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=min(len(descriptors), worker_count))

    def collect(future: concurrent.futures.Future[ServiceRecord]) -> None:
        collected.add(future)
        index = future_map[future]
        try:
            records_by_index[index] = future.result()
        except BaseException as exc:  # noqa: BLE001 - a worker cancellation is transaction data
            failures_by_index[index] = exc

    try:
        try:
            for index, descriptor in enumerate(descriptors):
                future = executor.submit(start_record, descriptor)
                future_map[future] = index
            for future in concurrent.futures.as_completed(future_map):
                collect(future)
        except BaseException as exc:  # noqa: BLE001 - main-thread cancellation must drain submitted launches
            interruption = exc
            for future in future_map:
                if future not in collected:
                    future.cancel()
    finally:
        try:
            executor.shutdown(wait=True, cancel_futures=interruption is not None)
        except BaseException as exc:  # noqa: BLE001 - preserve the first cancellation and retry teardown
            if interruption is None:
                interruption = exc
            for future in future_map:
                future.cancel()
            try:
                executor.shutdown(wait=True, cancel_futures=True)
            except BaseException as shutdown_exc:  # noqa: BLE001 - retain diagnostics on the original failure
                assert interruption is not None
                interruption.add_note(f"parallel executor shutdown failed: {shutdown_exc}")

    for future in future_map:
        if future in collected or future.cancelled():
            continue
        if future.done():
            collect(future)
    return records_by_index, failures_by_index, interruption


def _primary_parallel_failure(
    failures_by_index: dict[int, BaseException],
    *,
    interruption: BaseException | None,
) -> BaseException | None:
    if interruption is not None:
        return interruption
    cancellation_indexes = [
        index for index, failure in failures_by_index.items() if not isinstance(failure, Exception)
    ]
    if cancellation_indexes:
        return failures_by_index[min(cancellation_indexes)]
    if failures_by_index:
        return failures_by_index[min(failures_by_index)]
    return None


def _failed_start_record(
    *,
    project: str,
    service_type: str,
    cwd: str,
    pid: int | None,
    requested_port: int | None,
    listener_expected: bool,
    failure_detail: str,
) -> ServiceRecord:
    record = ServiceRecord(
        name=f"{project} {service_display_name(service_type)}",
        type=service_type,
        cwd=cwd,
        pid=pid,
        requested_port=requested_port,
        actual_port=None,
        status="termination_failed",
        started_at=time.time(),
        listener_expected=listener_expected,
        failure_detail=failure_detail,
        degraded=True,
    )
    record.project = project
    record.service_slug = service_type
    return record


def _unterminated_services_from_failures(
    failures: Iterable[object],
) -> dict[str, ServiceRecord]:
    unterminated: dict[str, ServiceRecord] = {}
    for failure in failures:
        services = getattr(failure, "unterminated_services", None)
        if not isinstance(services, dict):
            continue
        for name, service in services.items():
            if isinstance(name, str) and isinstance(service, ServiceRecord):
                unterminated[name] = service
    return unterminated
