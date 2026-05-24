from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping

_STATE_DIRNAME = ".envctl-state"


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
    return _read_json_object(path)


def _write_backend_bootstrap_state(*, backend_cwd: Path, state: dict[str, object]) -> None:
    _write_json_object(_backend_bootstrap_state_path(backend_cwd), state)


def _read_backend_runtime_prep_state(backend_cwd: Path) -> dict[str, object] | None:
    return _read_json_object(_backend_runtime_prep_state_path(backend_cwd))


def _write_backend_runtime_prep_state(*, backend_cwd: Path, state: dict[str, object]) -> None:
    _write_json_object(_backend_runtime_prep_state_path(backend_cwd), state)


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
    return _read_json_object(_frontend_runtime_prep_state_path(frontend_cwd))


def _write_frontend_runtime_prep_state(*, frontend_cwd: Path, state: dict[str, object]) -> None:
    _write_json_object(_frontend_runtime_prep_state_path(frontend_cwd), state)


def _read_json_object(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _write_json_object(path: Path, state: dict[str, object]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return
