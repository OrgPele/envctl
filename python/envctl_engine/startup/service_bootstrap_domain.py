from __future__ import annotations

# pyright: reportUnusedFunction=false

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from envctl_engine.shared.node_tooling import detect_package_manager, load_package_json
from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.parsing import parse_bool
from envctl_engine.startup.service_env_support import (
    _BACKEND_SENSITIVE_ENV_KEYS as _BACKEND_SENSITIVE_ENV_KEYS,
    _BackendEnvContract as _BackendEnvContract,
    _emit_backend_env_resolved as _emit_backend_env_resolved,
    _env_assignment_key as _env_assignment_key,
    _EnvFileResolution as _EnvFileResolution,
    _normalize_projected_backend_env as _normalize_projected_backend_env,
    _override_env_path as _override_env_path,
    _read_env_file_safe as _read_env_file_safe,
    _resolve_backend_env_contract as _resolve_backend_env_contract,
    _resolve_backend_env_file as _resolve_backend_env_file,
    _resolve_backend_env_file_resolution as _resolve_backend_env_file_resolution,
    _resolve_env_file_resolution as _resolve_env_file_resolution,
    _resolve_frontend_env_file as _resolve_frontend_env_file,
    _resolve_frontend_env_file_resolution as _resolve_frontend_env_file_resolution,
    _resolve_override_env_path_details as _resolve_override_env_path_details,
    _scrub_backend_sensitive_env as _scrub_backend_sensitive_env,
    _service_env_from_file as _service_env_from_file,
    _skip_local_db_env as _skip_local_db_env,
    _sync_backend_env_file as _sync_backend_env_file,
    _sync_frontend_local_env_file as _sync_frontend_local_env_file,
)
from envctl_engine.startup.public_urls import browser_backend_url, resolve_public_host
from envctl_engine.ui.path_links import render_path_for_terminal

_STATE_DIRNAME = ".envctl-state"


class ProjectContextLike(Protocol):
    name: str
    root: Path


def configured_service_types_for_mode(config: Any, runtime_mode: str) -> list[str]:
    if hasattr(config, "profile_for_mode"):
        profile = config.profile_for_mode(runtime_mode)
        configured: list[str] = []
        if bool(getattr(profile, "backend_enable", False)):
            configured.append("backend")
        if bool(getattr(profile, "frontend_enable", False)):
            configured.append("frontend")
        return configured
    return [
        service_name
        for service_name, enabled in (
            ("backend", config.service_enabled_for_mode(runtime_mode, "backend")),
            ("frontend", config.service_enabled_for_mode(runtime_mode, "frontend")),
        )
        if enabled
    ]


def _prepare_backend_runtime(
    self: Any,
    *,
    context: ProjectContextLike,
    backend_cwd: Path,
    backend_log_path: str,
    project_env_base: Mapping[str, str],
    route: Route | None,
    backend_env_file: Path | None,
    backend_env_is_default: bool,
) -> None:
    prepare_started = time.monotonic()
    requirements_file = backend_cwd / "requirements.txt"
    pyproject_file = backend_cwd / "pyproject.toml"
    manager = "poetry" if pyproject_file.is_file() and self._command_exists("poetry") else "pip"
    env_contract = _resolve_backend_env_contract(
        self,
        context=context,
        backend_cwd=backend_cwd,
        base_env=self._command_env(port=0),
        projected_env=project_env_base,
    )
    env = env_contract.env
    env_merge_started = time.monotonic()
    if (
        env_contract.env_file_path is not None
        and env_contract.env_file_path.is_file()
        and env_contract.env_file_is_default
        and not env_contract.skip_local_db_env
    ):
        self._sync_backend_env_file(env_contract.env_file_path, env=env)
    _emit_bootstrap_phase(
        self,
        project=context.name,
        service="backend",
        phase="env_merge",
        started=env_merge_started,
    )

    uses_poetry = pyproject_file.is_file() and _pyproject_uses_poetry(pyproject_file) and self._command_exists("poetry")
    probe_modules = _backend_runtime_probe_modules(backend_cwd) if uses_poetry else ()

    def _poetry_environment_ready() -> bool:
        return _poetry_backend_environment_ready(
            self,
            backend_cwd=backend_cwd,
            env=env,
            modules=probe_modules,
        )

    poetry_install_decision: tuple[bool, str, dict[str, object]] | None = None
    poetry_install_check_emitted = False
    migrations_enabled = _backend_migrations_enabled(self, route)
    runtime_required, runtime_reason, runtime_state = _backend_runtime_prep_required(
        backend_cwd=backend_cwd,
        manager=manager,
        env=env,
        backend_env_file=env_contract.env_file_path,
        backend_env_is_default=env_contract.env_file_is_default,
        skip_local_db_env=env_contract.skip_local_db_env,
        migrations_enabled=migrations_enabled,
    )
    if not runtime_required:
        if uses_poetry:
            install_check_started = time.monotonic()
            poetry_install_decision = _backend_dependency_install_required(
                backend_cwd=backend_cwd,
                manager="poetry",
                environment_ready=_poetry_environment_ready if probe_modules else None,
            )
            install_required, install_reason, _install_state = poetry_install_decision
            _emit_bootstrap_phase(
                self,
                project=context.name,
                service="backend",
                phase="dependency_install_check",
                started=install_check_started,
                reason=install_reason,
            )
            poetry_install_check_emitted = True
            if not install_required:
                self._emit(
                    "service.bootstrap.skip",
                    project=context.name,
                    service="backend",
                    manager=manager,
                    step="install",
                    reason=install_reason,
                )
                _emit_bootstrap_phase(
                    self,
                    project=context.name,
                    service="backend",
                    phase="dependency_install",
                    started=time.monotonic(),
                    status="reused",
                    reason=install_reason,
                )
            else:
                runtime_required = True

        if not runtime_required:
            self._emit(
                "service.bootstrap.skip",
                project=context.name,
                service="backend",
                manager=manager,
                step="prepare",
                reason=runtime_reason,
            )
            _emit_bootstrap_phase(
                self,
                project=context.name,
                service="backend",
                phase="prepare",
                started=prepare_started,
                status="reused",
                reason=runtime_reason,
            )
            return

    if uses_poetry:
        install_check_started = time.monotonic()
        if poetry_install_decision is None:
            poetry_install_decision = _backend_dependency_install_required(
                backend_cwd=backend_cwd,
                manager="poetry",
                environment_ready=_poetry_environment_ready if probe_modules else None,
            )
        install_required, install_reason, install_state = poetry_install_decision
        if not poetry_install_check_emitted:
            _emit_bootstrap_phase(
                self,
                project=context.name,
                service="backend",
                phase="dependency_install_check",
                started=install_check_started,
                reason=install_reason,
            )
        if install_required:
            install_started = time.monotonic()
            self._emit(
                "service.bootstrap",
                project=context.name,
                service="backend",
                manager="poetry",
                step="install",
                reason=install_reason,
            )
            self._run_backend_bootstrap_command(
                context=context,
                command=["poetry", "install"],
                cwd=backend_cwd,
                backend_log_path=backend_log_path,
                env=env,
                step="poetry install",
            )
            _write_backend_bootstrap_state(backend_cwd=backend_cwd, state=install_state)
            _emit_bootstrap_phase(
                self,
                project=context.name,
                service="backend",
                phase="dependency_install",
                started=install_started,
                reason=install_reason,
            )
        else:
            self._emit(
                "service.bootstrap.skip",
                project=context.name,
                service="backend",
                manager="poetry",
                step="install",
                reason=install_reason,
            )
            _emit_bootstrap_phase(
                self,
                project=context.name,
                service="backend",
                phase="dependency_install",
                started=time.monotonic(),
                status="reused",
                reason=install_reason,
            )
        if migrations_enabled and self._backend_has_migrations(backend_cwd):
            migration_started = time.monotonic()
            self._emit("service.bootstrap", project=context.name, service="backend", manager="poetry", step="migrate")
            self._run_backend_migration_step(
                context=context,
                command=["poetry", "run", "alembic", "upgrade", "head"],
                cwd=backend_cwd,
                backend_log_path=backend_log_path,
                env=env,
                env_contract=env_contract,
                step="poetry alembic upgrade head",
            )
            _emit_bootstrap_phase(
                self,
                project=context.name,
                service="backend",
                phase="migration",
                started=migration_started,
            )
        else:
            _emit_bootstrap_phase(
                self,
                project=context.name,
                service="backend",
                phase="migration",
                started=time.monotonic(),
                status="skipped",
                reason="disabled_or_not_present",
            )
        _write_backend_runtime_prep_state(backend_cwd=backend_cwd, state=runtime_state)
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="backend",
            phase="prepare",
            started=prepare_started,
        )
        return

    if not requirements_file.is_file():
        return

    venv_dir = backend_cwd / "venv"
    venv_python = venv_dir / "bin" / "python"
    if not venv_python.exists():
        python_bin = self._default_python_executable()
        venv_started = time.monotonic()
        self._emit("service.bootstrap", project=context.name, service="backend", manager="venv", step="create")
        self._run_backend_bootstrap_command(
            context=context,
            command=[python_bin, "-m", "venv", str(venv_dir)],
            cwd=backend_cwd,
            backend_log_path=backend_log_path,
            env=env,
            step="python -m venv",
        )
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="backend",
            phase="venv_create",
            started=venv_started,
        )

    install_check_started = time.monotonic()
    install_required, install_reason, install_state = _backend_dependency_install_required(
        backend_cwd=backend_cwd,
        manager="pip",
    )
    _emit_bootstrap_phase(
        self,
        project=context.name,
        service="backend",
        phase="dependency_install_check",
        started=install_check_started,
        reason=install_reason,
    )
    if install_required:
        install_started = time.monotonic()
        self._emit(
            "service.bootstrap",
            project=context.name,
            service="backend",
            manager="pip",
            step="install",
            reason=install_reason,
        )
        self._run_backend_bootstrap_command(
            context=context,
            command=[str(venv_python), "-m", "pip", "install", "-r", "requirements.txt"],
            cwd=backend_cwd,
            backend_log_path=backend_log_path,
            env=env,
            step="pip install -r requirements.txt",
        )
        _write_backend_bootstrap_state(backend_cwd=backend_cwd, state=install_state)
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="backend",
            phase="dependency_install",
            started=install_started,
            reason=install_reason,
        )
    else:
        self._emit(
            "service.bootstrap.skip",
            project=context.name,
            service="backend",
            manager="pip",
            step="install",
            reason=install_reason,
        )
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="backend",
            phase="dependency_install",
            started=time.monotonic(),
            status="reused",
            reason=install_reason,
        )
    if migrations_enabled and self._backend_has_migrations(backend_cwd):
        migration_started = time.monotonic()
        self._emit("service.bootstrap", project=context.name, service="backend", manager="alembic", step="migrate")
        self._run_backend_migration_step(
            context=context,
            command=[str(venv_python), "-m", "alembic", "upgrade", "head"],
            cwd=backend_cwd,
            backend_log_path=backend_log_path,
            env=env,
            env_contract=env_contract,
            step="alembic upgrade head",
        )
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="backend",
            phase="migration",
            started=migration_started,
        )
    else:
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="backend",
            phase="migration",
            started=time.monotonic(),
            status="skipped",
            reason="disabled_or_not_present",
        )
    _write_backend_runtime_prep_state(backend_cwd=backend_cwd, state=runtime_state)
    _emit_bootstrap_phase(
        self,
        project=context.name,
        service="backend",
        phase="prepare",
        started=prepare_started,
    )


def _backend_migrations_enabled(self: Any, route: Route | None) -> bool:
    if route is None:
        raw = self.env.get("ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP") or self.config.raw.get(
            "ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP"
        )
        return parse_bool(raw, True)
    if bool(route.flags.get("_dependency_bootstrap_no_migrations")):
        return False
    if bool(route.flags.get("_resume_restore")):
        return False
    raw = self.env.get("ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP") or self.config.raw.get(
        "ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP"
    )
    return parse_bool(raw, True)


def _prepare_frontend_runtime(
    self: Any,
    *,
    context: ProjectContextLike,
    frontend_cwd: Path,
    frontend_log_path: str,
    project_env_base: Mapping[str, str],
    frontend_env_file: Path | None,
    backend_port: int,
    route: Route | None = None,
) -> None:
    prepare_started = time.monotonic()
    backend_url = ""
    api_url = ""
    manager = ""
    if backend_port > 0:
        backend_url = browser_backend_url(host=resolve_public_host(env=self.env, config=self.config), port=backend_port)
        api_url = f"{backend_url}/api/v1"

    package_json = frontend_cwd / "package.json"
    if not package_json.is_file():
        return

    payload = load_package_json(package_json)
    if payload is None:
        return
    scripts = payload.get("scripts")
    if not isinstance(scripts, dict):
        return
    dev_script = scripts.get("dev")
    if not isinstance(dev_script, str) or not dev_script.strip():
        return

    manager = detect_package_manager(frontend_cwd, command_exists=self._command_exists)
    if manager is None:
        return
    missing_dependency = _frontend_missing_direct_dependency(frontend_cwd=frontend_cwd, payload=payload)
    if missing_dependency is not None and not parse_bool(
        self.env.get("ENVCTL_SKIP_FRONTEND_DEPENDENCY_CHECK"),
        False,
    ):
        install_command, _fallback_command = _frontend_install_commands(frontend_cwd=frontend_cwd, manager=manager)
        command_text = " ".join(install_command)
        self._emit(
            "service.bootstrap.dependency_check",
            project=context.name,
            service="frontend",
            status="failed",
            package=missing_dependency,
            install_command=command_text,
        )
        raise RuntimeError(
            "frontend dependency check failed for "
            f"{context.name}: missing direct dependency {missing_dependency!r} in {frontend_cwd}. "
            f"Run `{command_text}` in {frontend_cwd}."
        )
    env = self._command_env(port=0, extra=project_env_base)
    if frontend_env_file is not None and frontend_env_file.is_file():
        loaded_env = self._read_env_file_safe(frontend_env_file)
        for key, value in loaded_env.items():
            env[key] = value
        env["APP_ENV_FILE"] = str(frontend_env_file)
    if backend_url:
        env["VITE_BACKEND_URL"] = backend_url
    if api_url:
        env["VITE_API_URL"] = api_url
    runtime_required, runtime_reason, runtime_state = _frontend_runtime_prep_required(
        frontend_cwd=frontend_cwd,
        manager=manager,
        env=env,
        dev_script=dev_script,
    )
    if not runtime_required:
        self._emit(
            "service.bootstrap.skip",
            project=context.name,
            service="frontend",
            manager=manager,
            step="prepare",
            reason=runtime_reason,
        )
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="frontend",
            phase="prepare",
            started=prepare_started,
            status="reused",
            reason=runtime_reason,
        )
        return
    install_check_started = time.monotonic()
    install_required, install_reason = _frontend_dependency_install_required(
        frontend_cwd=frontend_cwd,
        dev_script=dev_script,
    )
    _emit_bootstrap_phase(
        self,
        project=context.name,
        service="frontend",
        phase="dependency_install_check",
        started=install_check_started,
        reason=install_reason,
    )
    if not install_required:
        _write_frontend_runtime_prep_state(frontend_cwd=frontend_cwd, state=runtime_state)
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="frontend",
            phase="dependency_install",
            started=time.monotonic(),
            status="reused",
            reason=install_reason,
        )
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="frontend",
            phase="prepare",
            started=prepare_started,
        )
        return

    install_command, fallback_command = _frontend_install_commands(
        frontend_cwd=frontend_cwd,
        manager=manager,
    )
    install_started = time.monotonic()
    self._emit(
        "service.bootstrap",
        project=context.name,
        service="frontend",
        manager=manager,
        step="install",
        reason=install_reason,
    )
    try:
        self._run_frontend_bootstrap_command(
            context=context,
            command=install_command,
            cwd=frontend_cwd,
            frontend_log_path=frontend_log_path,
            env=env,
            step=f"{manager} install",
        )
    except RuntimeError:
        if not fallback_command:
            raise
        self._emit(
            "service.bootstrap.retry",
            project=context.name,
            service="frontend",
            step="install",
            reason="install_fallback",
        )
        self._run_frontend_bootstrap_command(
            context=context,
            command=fallback_command,
            cwd=frontend_cwd,
            frontend_log_path=frontend_log_path,
            env=env,
            step=f"{manager} install (fallback)",
        )
    _write_frontend_runtime_prep_state(frontend_cwd=frontend_cwd, state=runtime_state)
    _emit_bootstrap_phase(
        self,
        project=context.name,
        service="frontend",
        phase="dependency_install",
        started=install_started,
        reason=install_reason,
    )
    _emit_bootstrap_phase(
        self,
        project=context.name,
        service="frontend",
        phase="prepare",
        started=prepare_started,
    )


def _run_frontend_bootstrap_command(
    self: Any,
    *,
    context: ProjectContextLike,
    command: list[str],
    cwd: Path,
    frontend_log_path: str,
    env: Mapping[str, str],
    step: str,
) -> None:
    result = self.process_runner.run(
        command,
        cwd=cwd,
        env=env,
        timeout=300.0,
    )
    if result.returncode == 0:
        return
    error = self._command_result_error_text(result=result)
    if frontend_log_path:
        try:
            Path(frontend_log_path).parent.mkdir(parents=True, exist_ok=True)
            with Path(frontend_log_path).open("a", encoding="utf-8") as handle:
                handle.write(f"[envctl] frontend bootstrap step failed ({step}): {error}\n")
        except OSError:
            pass
    log_hint = f" Log: {frontend_log_path}" if frontend_log_path else ""
    raise RuntimeError(f"frontend bootstrap failed for {context.name} during {step}: {error}{log_hint}")


def _frontend_dependency_install_required(*, frontend_cwd: Path, dev_script: str) -> tuple[bool, str]:
    node_modules_dir = frontend_cwd / "node_modules"
    if not node_modules_dir.is_dir():
        return True, "node_modules_missing"

    if "vite" in dev_script.lower():
        vite_bin = node_modules_dir / ".bin" / "vite"
        if not vite_bin.is_file():
            return True, "vite_binary_missing"
    return False, "up_to_date"


def _frontend_missing_direct_dependency(*, frontend_cwd: Path, payload: Mapping[str, object]) -> str | None:
    node_modules_dir = frontend_cwd / "node_modules"
    if not node_modules_dir.is_dir():
        return None
    declared: list[str] = []
    for section_name in ("dependencies", "devDependencies"):
        section = payload.get(section_name)
        if not isinstance(section, dict):
            continue
        for package_name in section:
            name = str(package_name).strip()
            if name and not name.startswith("@types/"):
                declared.append(name)
    for package_name in sorted(set(declared)):
        if not _frontend_dependency_installed(node_modules_dir=node_modules_dir, package_name=package_name):
            return package_name
    return None


def _frontend_dependency_installed(*, node_modules_dir: Path, package_name: str) -> bool:
    package_path = node_modules_dir
    for part in package_name.split("/"):
        if not part:
            return False
        package_path = package_path / part
    return package_path.exists()


def _frontend_install_commands(*, frontend_cwd: Path, manager: str) -> tuple[list[str], list[str] | None]:
    if manager == "bun":
        return ["bun", "install"], None

    if manager == "pnpm":
        if (frontend_cwd / "pnpm-lock.yaml").is_file():
            return ["pnpm", "install", "--frozen-lockfile"], None
        return ["pnpm", "install"], None

    if manager == "yarn":
        if (frontend_cwd / "yarn.lock").is_file():
            return ["yarn", "install", "--frozen-lockfile"], None
        return ["yarn", "install"], None

    if (frontend_cwd / "package-lock.json").is_file():
        return (
            ["npm", "ci", "--include=dev", "--prefer-offline", "--no-audit"],
            ["npm", "install", "--include=dev"],
        )
    return ["npm", "install", "--include=dev"], None


def _pyproject_uses_poetry(pyproject_file: Path) -> bool:
    if not pyproject_file.is_file():
        return False
    try:
        text = pyproject_file.read_text(encoding="utf-8")
    except OSError:
        return False
    return "[tool.poetry]" in text or "[tool.pdm]" in text


def _backend_dependency_install_required(
    *,
    backend_cwd: Path,
    manager: str,
    environment_ready: Callable[[], bool] | None = None,
) -> tuple[bool, str, dict[str, object]]:
    fingerprint = _backend_dependency_fingerprint(backend_cwd=backend_cwd, manager=manager)
    state: dict[str, object] = {"manager": manager, "fingerprint": fingerprint}
    existing = _read_backend_bootstrap_state(backend_cwd)
    if manager == "poetry":
        if existing != state:
            return True, "dependency_files_changed", state
        if environment_ready is not None and not environment_ready():
            return True, "poetry_environment_missing_dependencies", state
        return False, "up_to_date", state

    env_artifact = backend_cwd / "venv"
    alt_env_artifact = backend_cwd / ".venv"
    if not env_artifact.exists() and not alt_env_artifact.exists():
        return True, "environment_missing", state
    if existing != state:
        return True, "dependency_files_changed", state
    return False, "up_to_date", state


def _backend_runtime_probe_modules(backend_cwd: Path) -> tuple[str, ...]:
    modules: list[str] = []
    for module in ("uvicorn",):
        if _backend_dependency_file_mentions(backend_cwd, module):
            modules.append(module)
    return tuple(modules)


def _backend_dependency_file_mentions(backend_cwd: Path, dependency_name: str) -> bool:
    normalized = dependency_name.replace("_", "[-_]")
    pattern = re.compile(rf"(^|[^A-Za-z0-9_.-]){normalized}([^A-Za-z0-9_.-]|$)", re.IGNORECASE)
    for candidate in (
        backend_cwd / "pyproject.toml",
        backend_cwd / "poetry.lock",
        backend_cwd / "requirements.txt",
    ):
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if pattern.search(text):
            return True
    return False


def _poetry_backend_environment_ready(
    self: Any,
    *,
    backend_cwd: Path,
    env: Mapping[str, str],
    modules: tuple[str, ...],
) -> bool:
    if not modules:
        return True
    imports = "; ".join(f"import {module}" for module in modules)
    try:
        result = self.process_runner.run(
            ["poetry", "run", "python", "-c", imports],
            cwd=backend_cwd,
            env=env,
            timeout=30.0,
        )
    except Exception:  # noqa: BLE001 - failed readiness probes should trigger a safe reinstall path.
        return False
    return int(getattr(result, "returncode", 1)) == 0


def _backend_runtime_prep_required(
    *,
    backend_cwd: Path,
    manager: str,
    env: Mapping[str, str],
    backend_env_file: Path | None,
    backend_env_is_default: bool,
    skip_local_db_env: bool,
    migrations_enabled: bool,
) -> tuple[bool, str, dict[str, object]]:
    state: dict[str, object] = {
        "manager": manager,
        "dependency_fingerprint": _backend_dependency_fingerprint(backend_cwd=backend_cwd, manager=manager),
        "runtime_fingerprint": _backend_runtime_fingerprint(
            backend_cwd=backend_cwd,
            env=env,
            backend_env_file=backend_env_file,
            backend_env_is_default=backend_env_is_default,
            skip_local_db_env=skip_local_db_env,
        ),
        "migrations_enabled": migrations_enabled,
    }
    existing = _read_backend_runtime_prep_state(backend_cwd)
    if migrations_enabled:
        return True, "migration_required", state
    if existing is None:
        return True, "bootstrap_cache_miss", state
    if str(existing.get("dependency_fingerprint", "")) != str(state["dependency_fingerprint"]):
        return True, "bootstrap_cache_miss", state
    if str(existing.get("runtime_fingerprint", "")) != str(state["runtime_fingerprint"]):
        return True, "env_changed", state
    return False, "service_stale_only", state


def _backend_dependency_fingerprint(*, backend_cwd: Path, manager: str) -> str:
    hasher = hashlib.sha256()
    hasher.update(manager.encode("utf-8"))
    for candidate in (
        backend_cwd / "pyproject.toml",
        backend_cwd / "poetry.lock",
        backend_cwd / "requirements.txt",
    ):
        hasher.update(candidate.name.encode("utf-8"))
        if not candidate.is_file():
            hasher.update(b"<missing>")
            continue
        try:
            hasher.update(candidate.read_bytes())
        except OSError:
            hasher.update(b"<unreadable>")
    return hasher.hexdigest()


def _backend_bootstrap_state_path(backend_cwd: Path) -> Path:
    return backend_cwd / _STATE_DIRNAME / "envctl-backend-bootstrap.json"


def _backend_runtime_prep_state_path(backend_cwd: Path) -> Path:
    return backend_cwd / _STATE_DIRNAME / "envctl-backend-runtime-prep.json"


def _read_backend_bootstrap_state(backend_cwd: Path) -> dict[str, object] | None:
    path = _backend_bootstrap_state_path(backend_cwd)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _write_backend_bootstrap_state(*, backend_cwd: Path, state: dict[str, object]) -> None:
    path = _backend_bootstrap_state_path(backend_cwd)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return


def _read_backend_runtime_prep_state(backend_cwd: Path) -> dict[str, object] | None:
    path = _backend_runtime_prep_state_path(backend_cwd)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _write_backend_runtime_prep_state(*, backend_cwd: Path, state: dict[str, object]) -> None:
    path = _backend_runtime_prep_state_path(backend_cwd)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return


def _backend_runtime_fingerprint(
    *,
    backend_cwd: Path,
    env: Mapping[str, str],
    backend_env_file: Path | None,
    backend_env_is_default: bool,
    skip_local_db_env: bool,
) -> str:
    hasher = hashlib.sha256()
    hasher.update(str(backend_cwd).encode("utf-8"))
    hasher.update(str(backend_env_is_default).encode("utf-8"))
    hasher.update(str(skip_local_db_env).encode("utf-8"))
    for key in (
        "DATABASE_URL",
        "REDIS_URL",
        "SQLALCHEMY_DATABASE_URL",
        "ASYNC_DATABASE_URL",
        "APP_ENV_FILE",
    ):
        hasher.update(key.encode("utf-8"))
        hasher.update(str(env.get(key, "")).encode("utf-8"))
    if backend_env_file is not None:
        hasher.update(str(backend_env_file).encode("utf-8"))
        try:
            stat_result = backend_env_file.stat()
            hasher.update(str(stat_result.st_mtime_ns).encode("utf-8"))
            hasher.update(str(stat_result.st_size).encode("utf-8"))
        except OSError:
            hasher.update(b"<missing>")
    return hasher.hexdigest()


def _frontend_runtime_prep_state_path(frontend_cwd: Path) -> Path:
    return frontend_cwd / _STATE_DIRNAME / "envctl-frontend-runtime-prep.json"


def _frontend_runtime_prep_required(
    *,
    frontend_cwd: Path,
    manager: str,
    env: Mapping[str, str],
    dev_script: str,
) -> tuple[bool, str, dict[str, object]]:
    state: dict[str, object] = {
        "manager": manager,
        "runtime_fingerprint": _frontend_runtime_fingerprint(
            frontend_cwd=frontend_cwd,
            env=env,
            dev_script=dev_script,
        ),
    }
    existing = _read_frontend_runtime_prep_state(frontend_cwd)
    if existing is None:
        return True, "bootstrap_cache_miss", state
    if str(existing.get("runtime_fingerprint", "")) != str(state["runtime_fingerprint"]):
        return True, "env_changed", state
    return False, "service_stale_only", state


def _frontend_runtime_fingerprint(
    *,
    frontend_cwd: Path,
    env: Mapping[str, str],
    dev_script: str,
) -> str:
    hasher = hashlib.sha256()
    hasher.update(str(frontend_cwd).encode("utf-8"))
    hasher.update(dev_script.encode("utf-8"))
    for candidate in (
        frontend_cwd / "package.json",
        frontend_cwd / "package-lock.json",
        frontend_cwd / "pnpm-lock.yaml",
        frontend_cwd / "yarn.lock",
        frontend_cwd / "bun.lockb",
        frontend_cwd / ".env.local",
    ):
        hasher.update(candidate.name.encode("utf-8"))
        if not candidate.exists():
            hasher.update(b"<missing>")
            continue
        try:
            stat_result = candidate.stat()
            hasher.update(str(stat_result.st_mtime_ns).encode("utf-8"))
            hasher.update(str(stat_result.st_size).encode("utf-8"))
        except OSError:
            hasher.update(b"<unreadable>")
    for key in ("VITE_BACKEND_URL", "VITE_API_URL", "APP_ENV_FILE"):
        hasher.update(key.encode("utf-8"))
        hasher.update(str(env.get(key, "")).encode("utf-8"))
    return hasher.hexdigest()


def _read_frontend_runtime_prep_state(frontend_cwd: Path) -> dict[str, object] | None:
    path = _frontend_runtime_prep_state_path(frontend_cwd)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _write_frontend_runtime_prep_state(*, frontend_cwd: Path, state: dict[str, object]) -> None:
    path = _frontend_runtime_prep_state_path(frontend_cwd)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return


def _bootstrap_failure_suggestion(step: str, error: str, cwd: Path) -> str:
    lower_error = error.lower()
    if "poetry install" in step.lower() or "poetry" in lower_error:
        if "set `packages`" in error or "no packages found" in lower_error:
            return (
                f"\nTip: this project has pyproject.toml but does not use Poetry.\n"
                f"Fix: create a venv manually in {cwd}:\n"
                f"  python -m venv venv && source venv/bin/activate && pip install -e .\n"
                f"Or add TREES_BACKEND_ENABLE=false to your .envctl to skip backend bootstrap."
            )
        if "lock file" in lower_error or "poetry.lock" in lower_error:
            return (
                f"\nTip: Poetry lock file is missing. Run `poetry lock` in {cwd},\n"
                f"or set TREES_BACKEND_ENABLE=false in .envctl to skip bootstrap."
            )
        return (
            "\nTip: Poetry install failed. Check that the project is configured for Poetry.\n"
            "If this project uses pip/setuptools instead, add TREES_BACKEND_ENABLE=false to .envctl."
        )
    if "pip install" in lower_error or "pip" in lower_error:
        return (
            f"\nTip: pip install failed. Check that requirements.txt or pyproject.toml is valid in {cwd}."
        )
    return ""


def _run_backend_bootstrap_command(
    self: Any,
    *,
    context: ProjectContextLike,
    command: list[str],
    cwd: Path,
    backend_log_path: str,
    env: Mapping[str, str],
    step: str,
) -> None:
    result = self.process_runner.run(
        command,
        cwd=cwd,
        env=env,
        timeout=300.0,
    )
    if result.returncode == 0:
        return
    error = self._command_result_error_text(result=result)
    if backend_log_path:
        try:
            Path(backend_log_path).parent.mkdir(parents=True, exist_ok=True)
            with Path(backend_log_path).open("a", encoding="utf-8") as handle:
                handle.write(f"[envctl] backend bootstrap step failed ({step}): {error}\n")
        except OSError:
            pass
    suggestion = _bootstrap_failure_suggestion(step, error, cwd)
    log_hint = f"\nLog: {backend_log_path}" if backend_log_path else ""
    raise RuntimeError(f"backend bootstrap failed for {context.name} during {step}: {error}{log_hint}\n{suggestion}")


def _run_backend_migration_step(
    self: Any,
    *,
    context: ProjectContextLike,
    command: list[str],
    cwd: Path,
    backend_log_path: str,
    env: Mapping[str, str],
    env_contract: _BackendEnvContract | None = None,
    step: str,
) -> None:
    try:
        self._run_backend_bootstrap_command(
            context=context,
            command=command,
            cwd=cwd,
            backend_log_path=backend_log_path,
            env=env,
            step=step,
        )
        return
    except RuntimeError as exc:
        retry_env = self._backend_migration_retry_env_for_async_driver_mismatch(
            env=env,
            error_message=str(exc),
        )
        if retry_env is not None:
            self._emit(
                "service.bootstrap.retry",
                project=context.name,
                service="backend",
                step=step,
                reason="async_driver_mismatch",
            )
            self._run_backend_bootstrap_command(
                context=context,
                command=command,
                cwd=cwd,
                backend_log_path=backend_log_path,
                env=retry_env,
                step=f"{step} (async driver fallback)",
            )
            return
        if self._backend_bootstrap_strict():
            raise
        message = str(exc)
        record_warning = getattr(self, "_record_project_startup_warning", None)
        if callable(record_warning):
            record_warning(
                context.name,
                f"Warning: backend migration step failed; continuing without migration ({message})",
            )
            if backend_log_path:
                record_warning(context.name, f"backend log: {backend_log_path}")
            detail = _backend_env_warning_line(env_contract)
            if detail is not None:
                record_warning(context.name, detail)
        else:
            print(
                f"Warning: backend migration step failed for {context.name}; continuing without migration ({message})"
            )
            if backend_log_path:
                print("  backend log:")
                rendered_path = render_path_for_terminal(backend_log_path, env=getattr(self, "env", {}))
                print(f"  {rendered_path}")
            detail = _backend_env_warning_line(env_contract)
            if detail is not None:
                print(detail)
        missing_revision = _backend_missing_revision_id(message)
        if missing_revision:
            hint_text = (
                "hint: alembic revision "
                f"{missing_revision} is missing in this worktree history. "
                f"Inspect migration chain in {cwd} "
                "(`alembic heads`, `alembic history`), then align DB revision "
                "(for local dev only, `alembic stamp head` can unblock)."
            )
            if callable(record_warning):
                record_warning(context.name, hint_text)
            else:
                print(f"  {hint_text}")
        self._emit(
            "service.bootstrap.warning",
            project=context.name,
            service="backend",
            step=step,
            error=message,
            backend_log_path=backend_log_path,
            missing_revision=missing_revision,
            env_file_path=str(env_contract.env_file_path) if env_contract and env_contract.env_file_path else None,
            env_file_source=env_contract.env_file_source if env_contract else None,
            override_resolution=env_contract.override_resolution if env_contract else None,
        )


def _backend_env_warning_line(env_contract: _BackendEnvContract | None) -> str | None:
    if env_contract is None:
        return None
    parts = [f"backend env source: {env_contract.env_file_source}"]
    if env_contract.env_file_path is not None:
        parts.append(str(env_contract.env_file_path))
    if env_contract.override_requested:
        parts.append(f"override_resolution={env_contract.override_resolution}")
    return " | ".join(parts)


def _backend_migration_retry_env_for_async_driver_mismatch(
    self: Any,
    *,
    env: Mapping[str, str],
    error_message: str,
) -> dict[str, str] | None:
    if not self._backend_async_driver_mismatch_error(error_message):
        return None
    current_url = str(env.get("DATABASE_URL", "")).strip()
    rewritten_url = self._rewrite_database_url_to_asyncpg(current_url)
    if rewritten_url is None or rewritten_url == current_url:
        return None
    retry_env = dict(env)
    for key in ("DATABASE_URL", "SQLALCHEMY_DATABASE_URL", "ASYNC_DATABASE_URL"):
        retry_env[key] = rewritten_url
    return retry_env


def _backend_async_driver_mismatch_error(message: str) -> bool:
    normalized = (message or "").lower()
    mismatch_tokens = (
        "requires an async driver",
        "is not async",
        "loaded 'psycopg2'",
        'loaded "psycopg2"',
    )
    return any(token in normalized for token in mismatch_tokens)


def _backend_missing_revision_id(message: str) -> str | None:
    if not message:
        return None
    match = re.search(
        r"can't locate revision identified by ['\"]([^'\"]+)['\"]",
        str(message),
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    revision = str(match.group(1)).strip()
    return revision or None


def _rewrite_database_url_to_asyncpg(database_url: str) -> str | None:
    value = (database_url or "").strip()
    if not value:
        return None
    if value.startswith("postgresql+asyncpg://"):
        return value
    replacements = (
        ("postgresql+psycopg2://", "postgresql+asyncpg://"),
        ("postgresql+psycopg://", "postgresql+asyncpg://"),
        ("postgresql://", "postgresql+asyncpg://"),
        ("postgres://", "postgresql+asyncpg://"),
    )
    for source, target in replacements:
        if value.startswith(source):
            return target + value[len(source) :]
    return None


def _emit_bootstrap_phase(
    self: Any,
    *,
    project: str,
    service: str,
    phase: str,
    started: float,
    status: str = "ok",
    reason: str | None = None,
) -> None:
    emit = getattr(self, "_emit", None)
    if not callable(emit):
        return
    emit(
        "service.bootstrap.phase",
        project=project,
        service=service,
        phase=phase,
        status=status,
        reason=reason,
        duration_ms=round((time.monotonic() - started) * 1000.0, 2),
    )


def _backend_bootstrap_strict(self: Any) -> bool:
    raw = self.env.get("ENVCTL_BACKEND_BOOTSTRAP_STRICT") or self.config.raw.get("ENVCTL_BACKEND_BOOTSTRAP_STRICT")
    return parse_bool(raw, False)


def _backend_has_migrations(backend_cwd: Path) -> bool:
    migration_markers = (
        backend_cwd / "alembic.ini",
        backend_cwd / "alembic" / "versions",
        backend_cwd / "migrations" / "versions",
    )
    return any(marker.exists() for marker in migration_markers)
