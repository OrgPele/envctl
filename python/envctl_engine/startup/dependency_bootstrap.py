from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.service_bootstrap_domain import _pyproject_uses_poetry
from envctl_engine.state.models import RequirementsResult


@dataclass(frozen=True, slots=True)
class PreparedBackendRuntime:
    manager: str
    runner_prefix: tuple[str, ...]
    env_path: Path | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class PreparedFrontendRuntime:
    manager: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ProjectDependencyBootstrapResult:
    project: str
    backend: PreparedBackendRuntime
    frontend: PreparedFrontendRuntime
    prepared: bool
    skipped: tuple[str, ...] = ()


def prepare_project_dependencies(
    runtime: Any,
    *,
    context: Any,
    route: Route | None,
    run_id: str,
    requirements: RequirementsResult | None = None,
) -> ProjectDependencyBootstrapResult:
    """Prepare backend/frontend dependency artifacts without starting project services."""

    backend_cwd = _service_cwd(
        context_root=Path(context.root),
        configured_name=str(getattr(runtime.config, "backend_dir_name", "backend")),
    )
    frontend_cwd = _service_cwd(
        context_root=Path(context.root),
        configured_name=str(getattr(runtime.config, "frontend_dir_name", "frontend")),
    )
    run_logs_dir = runtime._run_dir_path(run_id)
    safe_project_name = str(context.name).replace("/", "_").replace(" ", "_")
    backend_log_path = str(run_logs_dir / f"{safe_project_name}_backend.txt")
    frontend_log_path = str(run_logs_dir / f"{safe_project_name}_frontend.txt")
    dependency_route = _dependency_bootstrap_route(route)
    project_requirements = requirements or RequirementsResult(project=str(context.name), health="dependency_bootstrap")
    project_env_internal = _project_env_internal(
        runtime,
        context=context,
        requirements=project_requirements,
        route=route,
    )
    frontend_project_env_base = _project_env(
        runtime,
        context=context,
        requirements=project_requirements,
        route=route,
        service_name="frontend",
    )
    backend_env_file, backend_env_is_default = runtime._resolve_backend_env_file(
        context=context,
        backend_cwd=backend_cwd,
    )
    frontend_env_file = runtime._resolve_frontend_env_file(
        context=context,
        frontend_cwd=frontend_cwd,
    )

    backend_plan = _backend_plan(runtime, backend_cwd)
    frontend_plan = _frontend_plan(runtime, frontend_cwd)
    skipped: list[str] = []
    prepare_dependencies = _route_launch_enabled(route, "launch_dependencies")
    prepare_backend = prepare_dependencies and _route_launch_enabled(route, "launch_backend")
    prepare_frontend = prepare_dependencies and _route_launch_enabled(route, "launch_frontend")
    if not prepare_backend:
        backend_plan = PreparedBackendRuntime(manager="skipped", runner_prefix=(), reason="disabled_by_flag")
        skipped.append("backend:disabled_by_flag")
    elif backend_plan.manager == "none":
        skipped.append(f"backend:{backend_plan.reason or 'no_dependency_manifest'}")
    else:
        runtime._prepare_backend_runtime(
            context=context,
            backend_cwd=backend_cwd,
            backend_log_path=backend_log_path,
            project_env_base=project_env_internal,
            route=dependency_route,
            backend_env_file=backend_env_file,
            backend_env_is_default=backend_env_is_default,
        )

    if not prepare_frontend:
        frontend_plan = PreparedFrontendRuntime(manager="skipped", reason="disabled_by_flag")
        skipped.append("frontend:disabled_by_flag")
    elif frontend_plan.manager == "none":
        skipped.append(f"frontend:{frontend_plan.reason or 'no_package_json'}")
    else:
        runtime._prepare_frontend_runtime(
            context=context,
            frontend_cwd=frontend_cwd,
            frontend_log_path=frontend_log_path,
            project_env_base=frontend_project_env_base,
            frontend_env_file=frontend_env_file,
            backend_port=_context_backend_port(context),
            route=dependency_route,
        )

    return ProjectDependencyBootstrapResult(
        project=str(context.name),
        backend=backend_plan,
        frontend=frontend_plan,
        prepared=backend_plan.manager not in {"none", "skipped"} or frontend_plan.manager not in {"none", "skipped"},
        skipped=tuple(skipped),
    )


def _route_launch_enabled(route: Route | None, flag_name: str) -> bool:
    if route is None:
        return True
    return route.flags.get(flag_name) is not False


def _dependency_bootstrap_route(route: Route | None) -> Route | None:
    if route is None:
        return None
    return Route(
        command=route.command,
        mode=route.mode,
        raw_args=route.raw_args,
        passthrough_args=route.passthrough_args,
        projects=route.projects,
        flags={**route.flags, "_dependency_bootstrap_no_migrations": True},
    )


def _service_cwd(*, context_root: Path, configured_name: str) -> Path:
    candidate = context_root / configured_name
    if candidate.is_dir():
        return candidate
    return context_root


def _backend_plan(runtime: Any, backend_cwd: Path) -> PreparedBackendRuntime:
    pyproject_file = backend_cwd / "pyproject.toml"
    requirements_file = backend_cwd / "requirements.txt"
    if pyproject_file.is_file() and _pyproject_uses_poetry(pyproject_file) and runtime._command_exists("poetry"):
        return PreparedBackendRuntime(
            manager="poetry",
            runner_prefix=("poetry", "run", "python"),
            reason="poetry_project",
        )
    if requirements_file.is_file():
        venv_python = backend_cwd / "venv" / "bin" / "python"
        return PreparedBackendRuntime(
            manager="venv",
            runner_prefix=(str(venv_python),),
            env_path=backend_cwd / "venv",
            reason="requirements_txt",
        )
    if pyproject_file.is_file():
        return PreparedBackendRuntime(manager="none", runner_prefix=(), reason="pyproject_without_available_poetry")
    return PreparedBackendRuntime(manager="none", runner_prefix=(), reason="no_backend_dependency_manifest")


def _frontend_plan(runtime: Any, frontend_cwd: Path) -> PreparedFrontendRuntime:
    package_json = frontend_cwd / "package.json"
    if not package_json.is_file():
        return PreparedFrontendRuntime(manager="none", reason="no_package_json")
    try:
        from envctl_engine.shared.node_tooling import detect_package_manager, load_package_json  # noqa: PLC0415

        payload = load_package_json(package_json)
    except Exception:
        return PreparedFrontendRuntime(manager="none", reason="invalid_package_json")
    scripts = payload.get("scripts") if isinstance(payload, dict) else None
    dev_script = scripts.get("dev") if isinstance(scripts, dict) else None
    if not isinstance(dev_script, str) or not dev_script.strip():
        return PreparedFrontendRuntime(manager="none", reason="missing_dev_script")
    manager = detect_package_manager(frontend_cwd, command_exists=runtime._command_exists)
    if manager is None:
        return PreparedFrontendRuntime(manager="none", reason="missing_package_manager")
    return PreparedFrontendRuntime(manager=manager, reason="dev_script")


def _project_env_internal(
    runtime: Any,
    *,
    context: Any,
    requirements: RequirementsResult,
    route: Route | None,
) -> dict[str, str]:
    builder = getattr(runtime, "_project_service_env_internal", None)
    if callable(builder):
        return cast(dict[str, str], builder(context, requirements=requirements, route=route))
    return runtime._project_service_env(context, requirements=requirements, route=route)


def _project_env(
    runtime: Any,
    *,
    context: Any,
    requirements: RequirementsResult,
    route: Route | None,
    service_name: str,
) -> dict[str, str]:
    try:
        return runtime._project_service_env(
            context,
            requirements=requirements,
            route=route,
            service_name=service_name,
        )
    except TypeError as exc:
        if "service_name" not in str(exc):
            raise
        return runtime._project_service_env(context, requirements=requirements, route=route)


def _context_backend_port(context: Any) -> int:
    ports = getattr(context, "ports", {}) or {}
    backend_plan = ports.get("backend") if isinstance(ports, dict) else None
    value = getattr(backend_plan, "final", 0)
    return value if isinstance(value, int) else 0
