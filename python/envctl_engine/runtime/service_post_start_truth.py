from __future__ import annotations

from typing import Any

from envctl_engine.runtime.service_status_truth import service_truth_status
from envctl_engine.runtime.service_truth_diagnostics import service_listener_failure_detail


def assert_project_services_post_start_truth(
    runtime: Any,
    *,
    context: Any,
    services: dict[str, object] | Any,
) -> None:
    if not runtime._listener_truth_enforced():
        return
    for service in services.values():
        if not bool(getattr(service, "critical", True)) and bool(getattr(service, "degraded", False)):
            if hasattr(service, "status"):
                setattr(service, "status", "degraded")
            continue

        status = service_truth_status(runtime, service)
        if hasattr(service, "status"):
            setattr(service, "status", status)
        if status in {"running", "simulated"}:
            continue

        failure_detail, event_payload = post_start_failure_context(
            runtime,
            context=context,
            service=service,
            status=status,
        )
        if not bool(getattr(service, "critical", True)):
            degrade_noncritical_service(service, failure_detail=failure_detail)
            runtime._emit(
                "service.failure",
                **event_payload,
                critical=False,
                degraded=True,
            )
            continue
        runtime._emit("service.failure", **event_payload)
        raise RuntimeError(failure_detail)


def post_start_failure_context(
    runtime: Any,
    *,
    context: Any,
    service: object,
    status: str,
) -> tuple[str, dict[str, object]]:
    service_name = str(getattr(service, "type", "service") or "service")
    pid = getattr(service, "pid", None)
    log_path = getattr(service, "log_path", None)
    detail = service_listener_failure_detail(
        runtime,
        log_path=log_path if isinstance(log_path, str) else None,
        pid=pid if isinstance(pid, int) else None,
    )
    port = runtime._service_port(service)
    port_label = str(port) if isinstance(port, int) and port > 0 else "n/a"
    suffix = f" ({detail})" if detail else ""
    failure_detail = f"{service_name} became {status} after startup for {context.name} on port {port_label}{suffix}"
    return failure_detail, {
        "project": context.name,
        "service": service_name,
        "failure_class": "post_start_truth_check",
        "status": status,
        "port": port,
        "detail": detail,
    }


def degrade_noncritical_service(service: object, *, failure_detail: str) -> None:
    if hasattr(service, "status"):
        setattr(service, "status", "degraded")
    if hasattr(service, "degraded"):
        setattr(service, "degraded", True)
    if hasattr(service, "failure_detail"):
        setattr(service, "failure_detail", failure_detail)
