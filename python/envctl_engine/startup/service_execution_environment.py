from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from envctl_engine.startup.requirements_execution import requirements_timing_enabled
from envctl_engine.startup.service_execution_policy import coerce_env_mapping


@dataclass(slots=True)
class ProjectServiceLogPaths:
    run_logs_dir: Path
    safe_project_name: str
    backend_log_path: str
    frontend_log_path: str


def resolve_service_workdirs(*, config: Any, project_root: Path) -> tuple[Path, Path]:
    backend_cwd = project_root / str(getattr(config, "backend_dir_name", "backend"))
    frontend_cwd = project_root / str(getattr(config, "frontend_dir_name", "frontend"))
    if not backend_cwd.is_dir():
        backend_cwd = project_root
    if not frontend_cwd.is_dir():
        frontend_cwd = project_root
    return backend_cwd, frontend_cwd


def project_service_log_paths(*, runtime: Any, run_id: str, project_name: str) -> ProjectServiceLogPaths:
    run_logs_dir = runtime._run_dir_path(run_id)
    safe_project_name = project_name.replace("/", "_").replace(" ", "_")
    return ProjectServiceLogPaths(
        run_logs_dir=run_logs_dir,
        safe_project_name=safe_project_name,
        backend_log_path=str(run_logs_dir / f"{safe_project_name}_backend.txt"),
        frontend_log_path=str(run_logs_dir / f"{safe_project_name}_frontend.txt"),
    )


def project_env_for_service(
    runtime: Any,
    context: Any,
    *,
    requirements: Any,
    route: Any,
    service_name: str,
) -> dict[str, str]:
    try:
        raw = runtime._project_service_env(
            context,
            requirements=requirements,
            route=route,
            service_name=service_name,
        )
    except TypeError as exc:
        if "service_name" not in str(exc):
            raise
        raw = runtime._project_service_env(context, requirements=requirements, route=route)
    return coerce_env_mapping(raw, source=f"{service_name} project service env")


def configured_service_types_for_mode(runtime: Any, effective_mode: str, project_root: Path) -> set[str]:
    all_service_names_for_mode = getattr(runtime.config, "all_app_service_names_for_mode", None)
    if callable(all_service_names_for_mode):
        try:
            raw_names = all_service_names_for_mode(effective_mode, project_root=project_root)
            names = cast(list[str] | tuple[str, ...] | set[str], raw_names)
            return {
                service_name
                for service_name in names
            }
        except TypeError:
            raw_names = all_service_names_for_mode(effective_mode)
            names = cast(list[str] | tuple[str, ...] | set[str], raw_names)
            return {service_name for service_name in names}
    return {
        service_name
        for service_name in ("backend", "frontend")
        if runtime._service_enabled_for_mode(effective_mode, service_name)
    }


def make_service_dependency_emitter(
    *,
    orchestrator: Any,
    runtime: Any,
    route: Any,
) -> Any:
    def emit_service_dependency(**payload: object) -> None:
        runtime._emit("service.dependency.selected", **payload)
        if requirements_timing_enabled(orchestrator, route) and not orchestrator._suppress_timing_output(route):
            print(
                "Starting dependency service "
                f"{payload.get('dependency')} because {payload.get('service')} depends_on={payload.get('dependency')}"
            )

    return emit_service_dependency


def make_service_retry_emitter(*, runtime: Any, project_name: str) -> Any:
    def on_service_retry(
        service_type: str,
        failed_port: int,
        retry_port: int,
        attempt: int,
        error: str | None,
    ) -> None:
        runtime._emit(
            "service.retry",
            project=project_name,
            service=service_type,
            failed_port=failed_port,
            retry_port=retry_port,
            attempt=attempt,
            error=(error or "").strip() or None,
        )

    return on_service_retry
