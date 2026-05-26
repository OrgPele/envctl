from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from envctl_engine.runtime.command_models import Route
from envctl_engine.shared.python_project_metadata import pyproject_uses_poetry
from envctl_engine.startup.service_execution_environment import project_env_for_service
from envctl_engine.startup.service_execution_policy import resolve_project_service_env
from envctl_engine.state.models import RequirementsResult


class _DependencyBootstrapConfig(Protocol):
    backend_dir_name: str
    frontend_dir_name: str


class _ProjectContextLike(Protocol):
    name: str
    root: Path


class _BackendEnvFileResolver(Protocol):
    def __call__(self, *, context: _ProjectContextLike, backend_cwd: Path) -> tuple[Path | None, bool]: ...


class _FrontendEnvFileResolver(Protocol):
    def __call__(self, *, context: _ProjectContextLike, frontend_cwd: Path) -> Path | None: ...


class _BackendRuntimePreparer(Protocol):
    def __call__(
        self,
        *,
        context: _ProjectContextLike,
        backend_cwd: Path,
        backend_log_path: str,
        project_env_base: Mapping[str, str],
        route: Route | None,
        backend_env_file: Path | None,
        backend_env_is_default: bool,
    ) -> None: ...


class _FrontendRuntimePreparer(Protocol):
    def __call__(
        self,
        *,
        context: _ProjectContextLike,
        frontend_cwd: Path,
        frontend_log_path: str,
        project_env_base: Mapping[str, str],
        frontend_env_file: Path | None,
        backend_port: int,
        route: Route | None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class _DependencyBootstrapServices:
    config: _DependencyBootstrapConfig
    run_dir_path: Callable[[str], Path]
    command_exists: Callable[[str], bool]
    resolve_backend_env_file: _BackendEnvFileResolver
    resolve_frontend_env_file: _FrontendEnvFileResolver
    prepare_backend_runtime: _BackendRuntimePreparer
    prepare_frontend_runtime: _FrontendRuntimePreparer


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


def _dependency_bootstrap_services(runtime: object) -> _DependencyBootstrapServices:
    return _DependencyBootstrapServices(
        config=cast(_DependencyBootstrapConfig, getattr(runtime, "config")),
        run_dir_path=cast(Callable[[str], Path], _required_runtime_callable(runtime, "_run_dir_path")),
        command_exists=cast(Callable[[str], bool], _required_runtime_callable(runtime, "_command_exists")),
        resolve_backend_env_file=cast(
            _BackendEnvFileResolver,
            _required_runtime_callable(runtime, "_resolve_backend_env_file"),
        ),
        resolve_frontend_env_file=cast(
            _FrontendEnvFileResolver,
            _required_runtime_callable(runtime, "_resolve_frontend_env_file"),
        ),
        prepare_backend_runtime=cast(
            _BackendRuntimePreparer,
            _required_runtime_callable(runtime, "_prepare_backend_runtime"),
        ),
        prepare_frontend_runtime=cast(
            _FrontendRuntimePreparer,
            _required_runtime_callable(runtime, "_prepare_frontend_runtime"),
        ),
    )


def _required_runtime_callable(runtime: object, name: str) -> Callable[..., object]:
    method = getattr(runtime, name, None)
    if not callable(method):
        raise TypeError(f"runtime must provide callable {name}")
    return method


def prepare_project_dependencies(
    runtime: object,
    *,
    context: _ProjectContextLike,
    route: Route | None,
    run_id: str,
    requirements: RequirementsResult | None = None,
) -> ProjectDependencyBootstrapResult:
    """Prepare backend/frontend dependency artifacts without starting project services."""

    services = _dependency_bootstrap_services(runtime)
    backend_cwd = _service_cwd(
        context_root=Path(context.root),
        configured_name=str(getattr(services.config, "backend_dir_name", "backend")),
    )
    frontend_cwd = _service_cwd(
        context_root=Path(context.root),
        configured_name=str(getattr(services.config, "frontend_dir_name", "frontend")),
    )
    run_logs_dir = services.run_dir_path(run_id)
    safe_project_name = str(context.name).replace("/", "_").replace(" ", "_")
    backend_log_path = str(run_logs_dir / f"{safe_project_name}_backend.txt")
    frontend_log_path = str(run_logs_dir / f"{safe_project_name}_frontend.txt")
    dependency_route = _dependency_bootstrap_route(route)
    project_requirements = requirements or RequirementsResult(project=str(context.name), health="dependency_bootstrap")
    project_env_internal = resolve_project_service_env(
        runtime,
        context=context,
        requirements=project_requirements,
        route=route,
    )
    frontend_project_env_base = project_env_for_service(
        runtime,
        context,
        requirements=project_requirements,
        route=route,
        service_name="frontend",
    )
    backend_env_file, backend_env_is_default = services.resolve_backend_env_file(
        context=context,
        backend_cwd=backend_cwd,
    )
    frontend_env_file = services.resolve_frontend_env_file(
        context=context,
        frontend_cwd=frontend_cwd,
    )

    backend_plan = _backend_plan(command_exists=services.command_exists, backend_cwd=backend_cwd)
    frontend_plan = _frontend_plan(command_exists=services.command_exists, frontend_cwd=frontend_cwd)
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
        services.prepare_backend_runtime(
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
        services.prepare_frontend_runtime(
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


def _backend_plan(*, command_exists: Callable[[str], bool], backend_cwd: Path) -> PreparedBackendRuntime:
    pyproject_file = backend_cwd / "pyproject.toml"
    requirements_file = backend_cwd / "requirements.txt"
    if pyproject_uses_poetry(pyproject_file) and command_exists("poetry"):
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


def _frontend_plan(*, command_exists: Callable[[str], bool], frontend_cwd: Path) -> PreparedFrontendRuntime:
    package_json = frontend_cwd / "package.json"
    if not package_json.is_file():
        return PreparedFrontendRuntime(manager="none", reason="no_package_json")
    try:
        from envctl_engine.shared.node_tooling import detect_package_manager, load_package_json  # noqa: PLC0415

        payload: object = load_package_json(package_json)
    except Exception:
        return PreparedFrontendRuntime(manager="none", reason="invalid_package_json")
    scripts: object = payload.get("scripts") if isinstance(payload, Mapping) else None
    dev_script = cast(Mapping[str, object], scripts).get("dev") if isinstance(scripts, Mapping) else None
    if not isinstance(dev_script, str) or not dev_script.strip():
        return PreparedFrontendRuntime(manager="none", reason="missing_dev_script")
    manager = detect_package_manager(frontend_cwd, command_exists=command_exists)
    if manager is None:
        return PreparedFrontendRuntime(manager="none", reason="missing_package_manager")
    return PreparedFrontendRuntime(manager=manager, reason="dev_script")


def _context_backend_port(context: _ProjectContextLike) -> int:
    ports = getattr(context, "ports", {})
    if not isinstance(ports, Mapping):
        return 0
    ports_by_name = cast(Mapping[str, object], ports)
    backend_plan = ports_by_name.get("backend")
    value = getattr(backend_plan, "final", 0)
    return value if isinstance(value, int) else 0
