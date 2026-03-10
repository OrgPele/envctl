from __future__ import annotations

# pyright: reportUnusedFunction=false

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Mapping, Protocol

from envctl_engine.shared.node_tooling import detect_package_manager, load_package_json
from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.parsing import parse_bool


class ProjectContextLike(Protocol):
    name: str
    root: Path


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
    env = self._command_env(port=0, extra=project_env_base)
    skip_local_db_env = self._skip_local_db_env(
        backend_env_file=backend_env_file,
        backend_env_is_default=backend_env_is_default,
    )
    env_merge_started = time.monotonic()
    if backend_env_file is not None and backend_env_file.is_file():
        loaded_env = self._read_env_file_safe(backend_env_file)
        for key, value in loaded_env.items():
            env[key] = value
        env["APP_ENV_FILE"] = str(backend_env_file)
    if not skip_local_db_env:
        database_url = project_env_base.get("DATABASE_URL")
        if isinstance(database_url, str) and database_url.strip():
            env["DATABASE_URL"] = database_url
    if not str(env.get("REDIS_URL", "")).strip():
        redis_url = project_env_base.get("REDIS_URL")
        if isinstance(redis_url, str) and redis_url.strip():
            env["REDIS_URL"] = redis_url
    if backend_env_file is not None and backend_env_file.is_file() and backend_env_is_default and not skip_local_db_env:
        self._sync_backend_env_file(backend_env_file, env=env)
    _emit_bootstrap_phase(
        self,
        project=context.name,
        service="backend",
        phase="env_merge",
        started=env_merge_started,
    )

    migrations_enabled = _backend_migrations_enabled(self, route)
    runtime_required, runtime_reason, runtime_state = _backend_runtime_prep_required(
        backend_cwd=backend_cwd,
        manager=manager,
        env=env,
        backend_env_file=backend_env_file,
        backend_env_is_default=backend_env_is_default,
        skip_local_db_env=skip_local_db_env,
        migrations_enabled=migrations_enabled,
    )
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

    if pyproject_file.is_file() and self._command_exists("poetry"):
        install_check_started = time.monotonic()
        install_required, install_reason, install_state = _backend_dependency_install_required(
            backend_cwd=backend_cwd,
            manager="poetry",
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
        return parse_bool(raw, False)
    if bool(route.flags.get("_resume_restore")):
        return False
    raw = self.env.get("ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP") or self.config.raw.get(
        "ENVCTL_BACKEND_MIGRATIONS_ON_STARTUP"
    )
    return parse_bool(raw, False)


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
        backend_url = f"http://localhost:{backend_port}"
        api_url = f"{backend_url}/api/v1"
        sync_started = time.monotonic()
        if _sync_frontend_local_env_file(
            frontend_cwd / ".env.local",
            api_url=api_url,
            backend_url=backend_url,
        ):
            self._emit(
                "service.bootstrap",
                project=context.name,
                service="frontend",
                manager="env",
                step="sync_env_local",
            )
        _emit_bootstrap_phase(
            self,
            project=context.name,
            service="frontend",
            phase="env_sync",
            started=sync_started,
        )

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
    raise RuntimeError(f"frontend bootstrap failed for {context.name} during {step}: {error}")


def _frontend_dependency_install_required(*, frontend_cwd: Path, dev_script: str) -> tuple[bool, str]:
    node_modules_dir = frontend_cwd / "node_modules"
    if not node_modules_dir.is_dir():
        return True, "node_modules_missing"

    if "vite" in dev_script.lower():
        vite_bin = node_modules_dir / ".bin" / "vite"
        if not vite_bin.is_file():
            return True, "vite_binary_missing"
    return False, "up_to_date"


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


def _backend_dependency_install_required(*, backend_cwd: Path, manager: str) -> tuple[bool, str, dict[str, object]]:
    fingerprint = _backend_dependency_fingerprint(backend_cwd=backend_cwd, manager=manager)
    state = {"manager": manager, "fingerprint": fingerprint}
    env_artifact = backend_cwd / "venv"
    alt_env_artifact = backend_cwd / ".venv"
    if not env_artifact.exists() and not alt_env_artifact.exists():
        return True, "environment_missing", state
    existing = _read_backend_bootstrap_state(backend_cwd)
    if existing != state:
        return True, "dependency_files_changed", state
    return False, "up_to_date", state


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
    state = {
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
    return backend_cwd / ".run-sh" / "envctl-backend-bootstrap.json"


def _backend_runtime_prep_state_path(backend_cwd: Path) -> Path:
    return backend_cwd / ".run-sh" / "envctl-backend-runtime-prep.json"


def _read_backend_bootstrap_state(backend_cwd: Path) -> dict[str, object] | None:
    path = _backend_bootstrap_state_path(backend_cwd)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


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
    return payload if isinstance(payload, dict) else None


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
    return frontend_cwd / ".run-sh" / "envctl-frontend-runtime-prep.json"


def _frontend_runtime_prep_required(
    *,
    frontend_cwd: Path,
    manager: str,
    env: Mapping[str, str],
    dev_script: str,
) -> tuple[bool, str, dict[str, object]]:
    state = {
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
    return payload if isinstance(payload, dict) else None


def _write_frontend_runtime_prep_state(*, frontend_cwd: Path, state: dict[str, object]) -> None:
    path = _frontend_runtime_prep_state_path(frontend_cwd)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return


def _sync_frontend_local_env_file(
    path: Path,
    *,
    api_url: str,
    backend_url: str,
) -> bool:
    updates = {
        "VITE_API_URL": api_url,
        "VITE_BACKEND_URL": backend_url,
    }
    try:
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    except OSError:
        return False

    replaced: set[str] = set()
    changed = False
    rendered: list[str] = []
    for line in lines:
        key = _env_assignment_key(line)
        if key is None or key not in updates or key in replaced:
            rendered.append(line)
            continue
        new_line = f"{key}={updates[key]}"
        if line != new_line:
            changed = True
        rendered.append(new_line)
        replaced.add(key)

    for key, value in updates.items():
        if key in replaced:
            continue
        rendered.append(f"{key}={value}")
        changed = True

    if not changed:
        return False

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def _service_env_from_file(
    self: Any,
    *,
    base_env: Mapping[str, str],
    env_file: Path | None,
    include_app_env_file: bool,
) -> dict[str, str]:
    merged = dict(base_env)
    if env_file is None or not env_file.is_file():
        return merged
    loaded_env = self._read_env_file_safe(env_file)
    for key, value in loaded_env.items():
        merged.setdefault(key, value)
    if include_app_env_file:
        merged["APP_ENV_FILE"] = str(env_file)
    return merged


def _resolve_backend_env_file(
    self: Any,
    *,
    context: ProjectContextLike,
    backend_cwd: Path,
) -> tuple[Path | None, bool]:
    override = self._override_env_path(
        self._command_override_value("BACKEND_ENV_FILE_OVERRIDE"),
        base_dir=context.root,
    )
    if override is None and context.name == "Main":
        override = self._override_env_path(
            self._command_override_value("MAIN_ENV_FILE_PATH"),
            base_dir=context.root,
        )
    if override is not None:
        return override, False
    default_env_file = backend_cwd / ".env"
    if default_env_file.is_file():
        return default_env_file, True
    return None, False


def _resolve_frontend_env_file(
    self: Any,
    *,
    context: ProjectContextLike,
    frontend_cwd: Path,
) -> Path | None:
    override = self._override_env_path(
        self._command_override_value("FRONTEND_ENV_FILE_OVERRIDE"),
        base_dir=context.root,
    )
    if override is None and context.name == "Main":
        override = self._override_env_path(
            self._command_override_value("MAIN_FRONTEND_ENV_FILE_PATH"),
            base_dir=context.root,
        )
    if override is not None:
        return override
    default_env_file = frontend_cwd / ".env"
    if default_env_file.is_file():
        return default_env_file
    return None


def _override_env_path(raw_path: str | None, *, base_dir: Path) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    candidate = Path(raw_path.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = (base_dir / candidate).resolve()
    if candidate.is_file():
        return candidate
    return None


def _skip_local_db_env(self: Any, *, backend_env_file: Path | None, backend_env_is_default: bool) -> bool:
    raw = self._command_override_value("SKIP_LOCAL_DB_ENV")
    skip = parse_bool(raw, False)
    if backend_env_file is not None and not backend_env_is_default:
        return True
    return skip


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
    raise RuntimeError(f"backend bootstrap failed for {context.name} during {step}: {error}")


def _run_backend_migration_step(
    self: Any,
    *,
    context: ProjectContextLike,
    command: list[str],
    cwd: Path,
    backend_log_path: str,
    env: Mapping[str, str],
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
        else:
            print(
                f"Warning: backend migration step failed for {context.name}; continuing without migration ({message})"
            )
            if backend_log_path:
                print(f"  backend log: {backend_log_path}")
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
        )


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
    retry_env["DATABASE_URL"] = rewritten_url
    sqlalchemy_url = str(retry_env.get("SQLALCHEMY_DATABASE_URL", "")).strip()
    if not sqlalchemy_url or sqlalchemy_url == current_url:
        retry_env["SQLALCHEMY_DATABASE_URL"] = rewritten_url
    async_url = str(retry_env.get("ASYNC_DATABASE_URL", "")).strip()
    if not async_url or async_url == current_url:
        retry_env["ASYNC_DATABASE_URL"] = rewritten_url
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


def _read_env_file_safe(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        key = _env_assignment_key(line)
        if key is None:
            continue
        assignment = line.strip()
        if assignment.startswith("export "):
            assignment = assignment[len("export ") :].strip()
        if "=" not in assignment:
            continue
        raw_value = assignment.split("=", 1)[1].strip()
        if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {"'", '"'}:
            raw_value = raw_value[1:-1]
        values[key] = raw_value
    return values


def _sync_backend_env_file(self: Any, path: Path, *, env: Mapping[str, str]) -> None:
    updates: dict[str, str] = {}
    for key in ("DATABASE_URL", "REDIS_URL"):
        value = env.get(key)
        if isinstance(value, str) and value.strip():
            updates[key] = value
    if not updates:
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    replaced: set[str] = set()
    changed = False
    rendered: list[str] = []
    for line in lines:
        key = self._env_assignment_key(line)
        if key is None or key not in updates or key in replaced:
            rendered.append(line)
            continue
        new_line = f"{key}={updates[key]}"
        if line != new_line:
            changed = True
        rendered.append(new_line)
        replaced.add(key)

    for key, value in updates.items():
        if key in replaced:
            continue
        rendered.append(f"{key}={value}")
        changed = True

    if not changed:
        return
    try:
        path.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    except OSError:
        return


def _env_assignment_key(line: str) -> str | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith("export "):
        text = text[len("export ") :].strip()
    if "=" not in text:
        return None
    key = text.split("=", 1)[0].strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        return None
    return key


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
