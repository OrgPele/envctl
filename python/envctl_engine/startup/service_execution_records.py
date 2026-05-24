from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from envctl_engine.state.models import ServiceRecord


class _PortPlanLike(Protocol):
    final: int


class _ProjectContextLike(Protocol):
    name: str
    ports: Mapping[str, _PortPlanLike]


class _AdditionalServiceLike(Protocol):
    name: str
    env_suffix: str


@dataclass(slots=True)
class PreparedServiceLaunch:
    service_name: str
    cwd: Path
    log_path: str
    requested_port: int
    env: dict[str, str]
    command_source: str | None
    listener_expected: bool = True


@dataclass(slots=True)
class LaunchedServiceRuntime:
    service_name: str
    requested_port: int
    actual_port: int
    pid: int | None
    log_path: str


def finalize_launched_service_records(
    *,
    context: _ProjectContextLike,
    records: dict[str, ServiceRecord],
    backend_plan: _PortPlanLike,
    frontend_plan: _PortPlanLike,
    additional_services: Iterable[_AdditionalServiceLike],
    prepared_launches: Mapping[str, PreparedServiceLaunch],
    backend_log_path: str,
    frontend_log_path: str,
    project_env_for_service: Callable[[str], dict[str, str]],
) -> list[LaunchedServiceRuntime]:
    launched_runtimes: list[LaunchedServiceRuntime] = []
    backend_record = records.get(f"{context.name} Backend")
    frontend_record = records.get(f"{context.name} Frontend")
    if backend_record is not None:
        backend_record.log_path = backend_log_path
        backend_plan.final = backend_record.actual_port or backend_plan.final
        launched_runtimes.append(
            LaunchedServiceRuntime(
                service_name="backend",
                requested_port=backend_record.requested_port or backend_plan.final,
                actual_port=backend_record.actual_port or backend_plan.final,
                pid=backend_record.pid,
                log_path=backend_log_path,
            )
        )
    if frontend_record is not None:
        frontend_record.log_path = frontend_log_path
        frontend_plan.final = frontend_record.actual_port or frontend_plan.final
        launched_runtimes.append(
            LaunchedServiceRuntime(
                service_name="frontend",
                requested_port=frontend_record.requested_port or frontend_plan.final,
                actual_port=frontend_record.actual_port or frontend_plan.final,
                pid=frontend_record.pid,
                log_path=frontend_log_path,
            )
        )
    for service in additional_services:
        display_name = " ".join(part.capitalize() for part in service.name.split("-") if part)
        record = records.get(f"{context.name} {display_name}")
        if record is None:
            continue
        launch = prepared_launches[service.name]
        record.log_path = launch.log_path
        plan = context.ports.get(service.name)
        if plan is not None and record.actual_port:
            plan.final = record.actual_port
        final_env = project_env_for_service(service.name)
        record.public_url = final_env.get(f"ENVCTL_SOURCE_SERVICE_{service.env_suffix}_PUBLIC_URL") or record.public_url
        record.health_url = final_env.get(f"ENVCTL_SOURCE_SERVICE_{service.env_suffix}_HEALTH_URL") or record.health_url
        launched_runtimes.append(
            LaunchedServiceRuntime(
                service_name=service.name,
                requested_port=record.requested_port or launch.requested_port,
                actual_port=record.actual_port or launch.requested_port,
                pid=record.pid,
                log_path=launch.log_path,
            )
        )
    return launched_runtimes
