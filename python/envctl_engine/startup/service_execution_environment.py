from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from envctl_engine.runtime.command_resolution import suggest_service_start_command
from envctl_engine.shared.artifact_names import safe_artifact_stem
from envctl_engine.startup.requirements_execution import requirements_timing_enabled
from envctl_engine.startup.service_execution_policy import coerce_env_mapping


_DEFAULT_APP_SERVICE_TYPES = frozenset({"backend", "frontend"})


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
    safe_project_name = safe_artifact_stem(project_name, fallback="project")
    return ProjectServiceLogPaths(
        run_logs_dir=run_logs_dir,
        safe_project_name=safe_project_name,
        backend_log_path=project_service_log_path(
            run_logs_dir=run_logs_dir,
            project_name=project_name,
            service_name="backend",
        ),
        frontend_log_path=project_service_log_path(
            run_logs_dir=run_logs_dir,
            project_name=project_name,
            service_name="frontend",
        ),
    )


def project_service_log_path(*, run_logs_dir: Path, project_name: object, service_name: object) -> str:
    safe_project_name = safe_artifact_stem(project_name, fallback="project")
    safe_service_name = safe_artifact_stem(str(service_name).replace("-", "_"), fallback="service")
    return str(run_logs_dir / f"{safe_project_name}_{safe_service_name}.txt")


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


def _route_runtime_scope(route: Any) -> str:
    if route is None:
        return ""
    return str(route.flags.get("runtime_scope") or "").strip().lower()


def _explicit_local_system_keys_for_mode(mode: str) -> set[str]:
    mode_prefix = "TREES" if str(mode).strip().lower() == "trees" else "MAIN"
    return {
        "ENVCTL_BACKEND_START_CMD",
        "ENVCTL_FRONTEND_START_CMD",
        "BACKEND_DIR",
        "FRONTEND_DIR",
        f"{mode_prefix}_STARTUP_ENABLE",
        f"{mode_prefix}_BACKEND_ENABLE",
        f"{mode_prefix}_FRONTEND_ENABLE",
    }


def _service_dependency_env_configured(config: Any, *, mode: str, service_name: str) -> bool:
    attr_prefixes = [service_name, f"{str(mode).strip().lower()}_{service_name}"]
    for attr_prefix in attr_prefixes:
        if bool(getattr(config, f"{attr_prefix}_dependency_env_section_present", False)):
            return True
        if tuple(getattr(config, f"{attr_prefix}_dependency_env_templates", ()) or ()):
            return True

    service_sections = getattr(config, "service_dependency_env_section_present", None)
    if isinstance(service_sections, dict) and bool(service_sections.get(service_name)):
        return True
    service_templates = getattr(config, "service_dependency_env_templates", None)
    if isinstance(service_templates, dict) and tuple(service_templates.get(service_name, ()) or ()):
        return True

    mode_key = (str(mode).strip().lower(), service_name)
    mode_sections = getattr(config, "mode_service_dependency_env_section_present", None)
    if isinstance(mode_sections, dict) and bool(mode_sections.get(mode_key)):
        return True
    mode_templates = getattr(config, "mode_service_dependency_env_templates", None)
    return isinstance(mode_templates, dict) and bool(tuple(mode_templates.get(mode_key, ()) or ()))


def no_local_app_system_configured(
    *,
    runtime: Any,
    context: Any,
    route: Any,
    mode: str,
    selected_service_types: set[str],
    configured_additional_services: tuple[object, ...],
) -> bool:
    if route is None or route.command != "plan":
        return False
    if _route_runtime_scope(route) != "entire-system":
        return False
    if not selected_service_types or not selected_service_types.issubset(_DEFAULT_APP_SERVICE_TYPES):
        return False
    if configured_additional_services:
        return False

    config = getattr(runtime, "config", None)
    if config is None:
        return False
    explicit_keys = {str(key).strip() for key in tuple(getattr(config, "explicit_keys", ()) or ())}
    if explicit_keys.intersection(_explicit_local_system_keys_for_mode(mode)):
        return False
    if tuple(getattr(config, "additional_services", ()) or ()):
        return False

    for service_name in sorted(selected_service_types):
        if _service_dependency_env_configured(config, mode=mode, service_name=service_name):
            return False
        if (
            suggest_service_start_command(
                service_name=service_name,
                project_root=context.root,
                command_exists=getattr(runtime, "_command_exists", None),
            )
            is not None
        ):
            return False
    return True


def maybe_skip_no_local_app_system(
    runtime: Any,
    context: Any,
    route: Any,
    mode: str,
    selected_service_types: set[str],
    configured_additional_services: tuple[object, ...],
) -> bool:
    if not no_local_app_system_configured(
        runtime=runtime,
        context=context,
        route=route,
        mode=mode,
        selected_service_types=selected_service_types,
        configured_additional_services=configured_additional_services,
    ):
        return False
    message = (
        "No local app system is configured for this repo/worktree; envctl is continuing with the "
        "implementation session only. --entire-system was honored, but there was nothing configured to start."
    )
    runtime._emit(
        "service.attach.skipped",
        project=context.name,
        mode=mode,
        reason="no_system_configured",
        requested_scope="entire-system",
        selected_default_services=sorted(selected_service_types),
    )
    record_warning = getattr(runtime, "_record_project_startup_warning", None)
    if callable(record_warning):
        record_warning(context.name, message)
    return True


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
