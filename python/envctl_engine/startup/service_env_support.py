from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Mapping

from envctl_engine.shared.parsing import parse_bool

_BACKEND_SENSITIVE_ENV_KEYS = (
    "APP_ENV_FILE",
    "DATABASE_URL",
    "REDIS_URL",
    "SQLALCHEMY_DATABASE_URL",
    "ASYNC_DATABASE_URL",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
)


@dataclass(frozen=True)
class _EnvFileResolution:
    path: Path | None
    is_default: bool
    source: str
    override_requested: bool
    override_resolution: str


@dataclass(frozen=True)
class _BackendEnvContract:
    env: dict[str, str]
    env_file_path: Path | None
    env_file_is_default: bool
    env_file_source: str
    override_requested: bool
    override_resolution: str
    override_authoritative: bool
    skip_local_db_env: bool
    scrubbed_keys: tuple[str, ...]
    projected_keys: tuple[str, ...]


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
    env_file_authoritative: bool = False,
) -> dict[str, str]:
    merged = dict(base_env)
    if env_file is None or not env_file.is_file():
        if include_app_env_file:
            merged["RUN_DB_MIGRATIONS_ON_STARTUP"] = "false"
        return merged
    loaded_env = self._read_env_file_safe(env_file)
    if env_file_authoritative:
        merged.update(loaded_env)
    else:
        for key, value in loaded_env.items():
            merged.setdefault(key, value)
    if include_app_env_file:
        merged["APP_ENV_FILE"] = str(env_file)
        merged["RUN_DB_MIGRATIONS_ON_STARTUP"] = "false"
    return merged


def _resolve_backend_env_file(
    self: Any,
    *,
    context: Any,
    backend_cwd: Path,
) -> tuple[Path | None, bool]:
    resolution = _resolve_backend_env_file_resolution(
        self,
        context=context,
        backend_cwd=backend_cwd,
    )
    return resolution.path, resolution.is_default


def _resolve_frontend_env_file(
    self: Any,
    *,
    context: Any,
    frontend_cwd: Path,
) -> Path | None:
    return _resolve_frontend_env_file_resolution(
        self,
        context=context,
        frontend_cwd=frontend_cwd,
    ).path


def _resolve_backend_env_file_resolution(
    self: Any,
    *,
    context: Any,
    backend_cwd: Path,
) -> _EnvFileResolution:
    override_raw = self._command_override_value("BACKEND_ENV_FILE_OVERRIDE")
    if override_raw is None and context.name == "Main":
        override_raw = self._command_override_value("MAIN_ENV_FILE_PATH")
    return _resolve_env_file_resolution(
        self,
        override_raw=override_raw,
        target_root=context.root,
        default_env_file=backend_cwd / ".env",
    )


def _resolve_frontend_env_file_resolution(
    self: Any,
    *,
    context: Any,
    frontend_cwd: Path,
) -> _EnvFileResolution:
    override_raw = self._command_override_value("FRONTEND_ENV_FILE_OVERRIDE")
    if override_raw is None and context.name == "Main":
        override_raw = self._command_override_value("MAIN_FRONTEND_ENV_FILE_PATH")
    return _resolve_env_file_resolution(
        self,
        override_raw=override_raw,
        target_root=context.root,
        default_env_file=frontend_cwd / ".env",
    )


def _resolve_env_file_resolution(
    self: Any,
    *,
    override_raw: str | None,
    target_root: Path,
    default_env_file: Path,
) -> _EnvFileResolution:
    override_requested = isinstance(override_raw, str) and bool(override_raw.strip())
    resolution = "none"
    override_path: Path | None = None
    if override_requested:
        override_path, resolution = _resolve_override_env_path_details(
            str(override_raw),
            target_root=target_root,
            repo_root=Path(str(getattr(self.config, "base_dir", target_root))),
        )
    if override_path is not None:
        return _EnvFileResolution(
            path=override_path,
            is_default=False,
            source="explicit_override",
            override_requested=override_requested,
            override_resolution=resolution,
        )
    if default_env_file.is_file():
        return _EnvFileResolution(
            path=default_env_file.resolve(),
            is_default=True,
            source="default",
            override_requested=override_requested,
            override_resolution=resolution,
        )
    return _EnvFileResolution(
        path=None,
        is_default=False,
        source="none",
        override_requested=override_requested,
        override_resolution=resolution,
    )


def _resolve_override_env_path_details(raw_path: str, *, target_root: Path, repo_root: Path) -> tuple[Path | None, str]:
    candidate = Path(raw_path.strip()).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved, "absolute"
        return None, "missing"

    target_candidate = (target_root / candidate).resolve()
    repo_candidate = (repo_root / candidate).resolve()
    target_exists = target_candidate.is_file()
    repo_exists = repo_candidate.is_file()

    if target_exists and repo_exists and target_candidate != repo_candidate:
        raise RuntimeError(
            "Relative env-file override is ambiguous; the path exists under both the target root and repo root. "
            "Use an absolute path."
        )
    if target_exists:
        return target_candidate, "target_root"
    if repo_exists:
        return repo_candidate, "repo_root"
    return None, "missing"


def _resolve_backend_env_contract(
    self: Any,
    *,
    context: Any,
    backend_cwd: Path,
    base_env: Mapping[str, str],
    projected_env: Mapping[str, str],
) -> _BackendEnvContract:
    env_resolution = _resolve_backend_env_file_resolution(
        self,
        context=context,
        backend_cwd=backend_cwd,
    )
    skip_local_db_env = _skip_local_db_env(
        self,
        backend_env_file=env_resolution.path,
        backend_env_is_default=env_resolution.is_default,
    )
    env, scrubbed_keys = _scrub_backend_sensitive_env(base_env)
    normalized_projected_env = _normalize_projected_backend_env(projected_env)
    env.update(normalized_projected_env)
    if env_resolution.path is not None and env_resolution.path.is_file():
        env.update(self._read_env_file_safe(env_resolution.path))
        env["APP_ENV_FILE"] = str(env_resolution.path)
    if not skip_local_db_env:
        for key, value in normalized_projected_env.items():
            if value.strip():
                env[key] = value
    env["RUN_DB_MIGRATIONS_ON_STARTUP"] = "false"
    contract = _BackendEnvContract(
        env=env,
        env_file_path=env_resolution.path,
        env_file_is_default=env_resolution.is_default,
        env_file_source=env_resolution.source,
        override_requested=env_resolution.override_requested,
        override_resolution=env_resolution.override_resolution,
        override_authoritative=(env_resolution.source == "explicit_override" and skip_local_db_env),
        skip_local_db_env=skip_local_db_env,
        scrubbed_keys=scrubbed_keys,
        projected_keys=tuple(sorted(normalized_projected_env)),
    )
    _emit_backend_env_resolved(
        self,
        context=context,
        backend_cwd=backend_cwd,
        contract=contract,
    )
    return contract


def _scrub_backend_sensitive_env(base_env: Mapping[str, str]) -> tuple[dict[str, str], tuple[str, ...]]:
    scrubbed: list[str] = []
    merged: dict[str, str] = {}
    for key, value in base_env.items():
        if key in _BACKEND_SENSITIVE_ENV_KEYS and isinstance(value, str) and value.strip():
            scrubbed.append(key)
            continue
        merged[str(key)] = str(value)
    return merged, tuple(sorted(scrubbed))


def _normalize_projected_backend_env(projected_env: Mapping[str, str]) -> dict[str, str]:
    normalized = {
        str(key): str(value)
        for key, value in projected_env.items()
        if isinstance(key, str) and isinstance(value, str) and value.strip()
    }
    database_url = normalized.get("DATABASE_URL")
    if isinstance(database_url, str) and database_url.strip():
        normalized.setdefault("SQLALCHEMY_DATABASE_URL", database_url)
        normalized.setdefault("ASYNC_DATABASE_URL", database_url)
    return normalized


def _emit_backend_env_resolved(
    self: Any,
    *,
    context: Any,
    backend_cwd: Path,
    contract: _BackendEnvContract,
) -> None:
    emitter = getattr(self, "_emit", None)
    if not callable(emitter):
        return
    emitter(
        "backend.env.resolved",
        project=context.name,
        project_root=str(context.root),
        backend_cwd=str(backend_cwd),
        env_file_path=str(contract.env_file_path) if contract.env_file_path is not None else None,
        env_file_source=contract.env_file_source,
        override_requested=contract.override_requested,
        override_resolution=contract.override_resolution,
        override_authoritative=contract.override_authoritative,
        scrubbed_keys=list(contract.scrubbed_keys),
        projected_keys=list(contract.projected_keys),
    )


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
    _ = env
    removals = {"SQLALCHEMY_DATABASE_URL", "ASYNC_DATABASE_URL"}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    replaced: set[str] = set()
    changed = False
    rendered: list[str] = []
    for line in lines:
        key = self._env_assignment_key(line)
        if key is None or key in replaced:
            rendered.append(line)
            continue
        if key in removals:
            changed = True
            replaced.add(key)
            continue
        rendered.append(line)

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
