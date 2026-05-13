from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from envctl_engine.requirements.core.models import DependencyDefinition
from envctl_engine.requirements.orchestrator import FailureClass, RequirementOutcome
from envctl_engine.shared.parsing import parse_bool


_DEPENDENCY_IDS = {"postgres", "redis", "supabase", "n8n"}
_MODE_EXTERNAL_VALUES = {"external", "externally-managed", "remote", "native-external"}


def dependency_external_mode(runtime: Any, dependency_id: str, *, mode: str | None = None) -> bool:
    dependency = _normalize_dependency_id(dependency_id)
    if not dependency:
        return False
    explicit_mode = _raw(runtime, f"ENVCTL_DEPENDENCY_{dependency.upper()}_MODE")
    if explicit_mode is None:
        explicit_mode = _raw(runtime, f"ENVCTL_{dependency.upper()}_MODE")
    if explicit_mode is not None:
        return str(explicit_mode).strip().lower() in _MODE_EXTERNAL_VALUES
    explicit_bool = _raw(runtime, f"ENVCTL_{dependency.upper()}_EXTERNAL")
    if explicit_bool is not None:
        return parse_bool(explicit_bool, False)
    external_list = _raw(runtime, "ENVCTL_EXTERNAL_DEPENDENCIES")
    if dependency in _parse_dependency_list(external_list):
        return True
    return _dependency_auto_external_mode(runtime, dependency, mode=mode)


def _dependency_auto_external_mode(runtime: Any, dependency_id: str, *, mode: str | None) -> bool:
    if str(mode or "").strip().lower() != "main":
        return False
    return external_dependency_validation_error(runtime, dependency_id) is None


def external_dependency_outcome(
    *,
    runtime: Any,
    definition: DependencyDefinition,
    plan: Any,
) -> RequirementOutcome:
    dependency = definition.id
    error = external_dependency_validation_error(runtime, dependency)
    resources = external_dependency_resources(runtime, definition)
    final_port = _primary_external_port(resources, definition) or int(getattr(plan, "final", 0) or 0)
    requested_port = int(getattr(plan, "requested", final_port) or final_port)
    return RequirementOutcome(
        service_name=dependency,
        success=error is None,
        requested_port=requested_port,
        final_port=final_port,
        retries=0,
        failure_class=FailureClass.HARD_START_FAILURE if error else None,
        error=error,
    )


def external_dependency_resources(runtime: Any, definition: DependencyDefinition) -> dict[str, int]:
    dependency = definition.id
    resources: dict[str, int] = {}
    if dependency == "postgres":
        _add_url_port(resources, "primary", _raw(runtime, "DATABASE_URL"))
    elif dependency == "redis":
        _add_url_port(resources, "primary", _raw(runtime, "REDIS_URL"))
    elif dependency == "n8n":
        _add_url_port(resources, "primary", _raw(runtime, "N8N_URL"))
    elif dependency == "supabase":
        _add_url_port(resources, "api", _raw(runtime, "SUPABASE_URL") or _raw(runtime, "SUPABASE_PUBLIC_URL"))
        _add_url_port(resources, "db", _raw(runtime, "DATABASE_URL"))
    for resource in definition.resources:
        value = resources.get(resource.name)
        if isinstance(value, int) and value > 0:
            resources.setdefault("primary", value)
            resources.setdefault("requested", value)
            break
    return resources


def external_dependency_project_env(runtime: Any, dependency_id: str) -> dict[str, str]:
    dependency = _normalize_dependency_id(dependency_id)
    if dependency == "postgres":
        return _external_postgres_env(runtime)
    if dependency == "redis":
        return _external_redis_env(runtime)
    if dependency == "n8n":
        return _external_n8n_env(runtime)
    if dependency == "supabase":
        return _external_supabase_env(runtime)
    return {}


def external_dependency_validation_error(runtime: Any, dependency_id: str) -> str | None:
    dependency = _normalize_dependency_id(dependency_id)
    if dependency == "postgres":
        return _missing_message("postgres", ("DATABASE_URL",), runtime)
    if dependency == "redis":
        return _missing_message("redis", ("REDIS_URL",), runtime)
    if dependency == "n8n":
        return _missing_message("n8n", ("N8N_URL",), runtime)
    if dependency == "supabase":
        missing = []
        if not (_raw(runtime, "SUPABASE_URL") or _raw(runtime, "SUPABASE_PUBLIC_URL")):
            missing.append("SUPABASE_URL")
        if not _raw(runtime, "SUPABASE_ANON_KEY"):
            missing.append("SUPABASE_ANON_KEY")
        if missing:
            return _format_missing("supabase", tuple(missing))
    return None


def external_dependency_url(runtime: Any, dependency_id: str) -> str | None:
    dependency = _normalize_dependency_id(dependency_id)
    if dependency == "postgres":
        return _raw(runtime, "DATABASE_URL")
    if dependency == "redis":
        return _raw(runtime, "REDIS_URL")
    if dependency == "n8n":
        return _raw(runtime, "N8N_URL")
    if dependency == "supabase":
        return _raw(runtime, "SUPABASE_URL") or _raw(runtime, "SUPABASE_PUBLIC_URL")
    return None


def _external_postgres_env(runtime: Any) -> dict[str, str]:
    env: dict[str, str] = {}
    database_url = _raw(runtime, "DATABASE_URL")
    if database_url:
        env["DATABASE_URL"] = database_url
        env["SQLALCHEMY_DATABASE_URL"] = _raw(runtime, "SQLALCHEMY_DATABASE_URL") or database_url
        env["ASYNC_DATABASE_URL"] = _raw(runtime, "ASYNC_DATABASE_URL") or database_url
        port = _url_port(database_url)
        if port is not None:
            env["DB_PORT"] = str(port)
    _copy_present(runtime, env, ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"))
    return env


def _external_redis_env(runtime: Any) -> dict[str, str]:
    env: dict[str, str] = {}
    redis_url = _raw(runtime, "REDIS_URL")
    if redis_url:
        env["REDIS_URL"] = redis_url
        port = _url_port(redis_url)
        if port is not None:
            env["REDIS_PORT"] = str(port)
    return env


def _external_n8n_env(runtime: Any) -> dict[str, str]:
    env: dict[str, str] = {}
    n8n_url = _raw(runtime, "N8N_URL")
    if n8n_url:
        env["N8N_URL"] = n8n_url
        port = _url_port(n8n_url)
        if port is not None:
            env["N8N_PORT"] = str(port)
    return env


def _external_supabase_env(runtime: Any) -> dict[str, str]:
    env: dict[str, str] = {}
    public_url = _raw(runtime, "SUPABASE_PUBLIC_URL") or _raw(runtime, "SUPABASE_URL")
    supabase_url = _raw(runtime, "SUPABASE_URL") or public_url
    if public_url:
        env["SUPABASE_PUBLIC_URL"] = public_url
        port = _url_port(public_url)
        if port is not None:
            env["SUPABASE_PUBLIC_PORT"] = str(port)
            env["SUPABASE_API_PORT"] = str(port)
    if supabase_url:
        env["SUPABASE_URL"] = supabase_url
        env.setdefault("SUPABASE_JWKS_URL", f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json")
    _copy_present(
        runtime,
        env,
        (
            "SUPABASE_ANON_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
            "SUPABASE_JWT_SECRET",
            "SUPABASE_JWKS_URL",
            "SUPABASE_DB_PASSWORD",
            "DB_HOST",
            "DB_USER",
            "DB_PASSWORD",
            "DB_NAME",
        ),
    )
    env.update(_external_postgres_env(runtime))
    if "DATABASE_URL" in env:
        db_port = _url_port(env["DATABASE_URL"])
        if db_port is not None:
            env["SUPABASE_DB_PORT"] = str(db_port)
            env.setdefault("DB_PORT", str(db_port))
    return env


def _raw(runtime: Any, key: str) -> str | None:
    runtime_env = getattr(runtime, "env", None)
    if isinstance(runtime_env, dict) and key in runtime_env:
        value = runtime_env.get(key)
        return str(value) if value else None
    config_raw = getattr(getattr(runtime, "config", None), "raw", None)
    if isinstance(config_raw, dict) and key in config_raw:
        value = config_raw.get(key)
        return str(value) if value else None
    override = getattr(runtime, "_command_override_value", None)
    if callable(override):
        value = override(key)
        if value:
            return str(value)
    app_env_value = _app_env_value(runtime, key)
    if app_env_value:
        return app_env_value
    return None


def _app_env_value(runtime: Any, key: str) -> str | None:
    for env_file in _candidate_app_env_files(runtime):
        values = _read_app_env_file(runtime, env_file)
        value = values.get(key)
        if value:
            return value
    return None


def _candidate_app_env_files(runtime: Any) -> tuple[Path, ...]:
    config = getattr(runtime, "config", None)
    base_dir = getattr(config, "base_dir", None)
    if not isinstance(base_dir, Path):
        return ()
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path | None) -> None:
        if path is None:
            return
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            resolved = path.expanduser()
        if resolved in seen:
            return
        seen.add(resolved)
        candidates.append(resolved)

    for key in ("BACKEND_ENV_FILE_OVERRIDE", "MAIN_ENV_FILE_PATH"):
        add(_resolve_env_file_path(runtime, key, base_dir=base_dir))
    backend_dir = str(getattr(config, "backend_dir_name", "backend") or "backend").strip() or "backend"
    add(base_dir / backend_dir / ".env")

    for key in ("FRONTEND_ENV_FILE_OVERRIDE", "MAIN_FRONTEND_ENV_FILE_PATH"):
        add(_resolve_env_file_path(runtime, key, base_dir=base_dir))
    frontend_dir = str(getattr(config, "frontend_dir_name", "frontend") or "frontend").strip() or "frontend"
    add(base_dir / frontend_dir / ".env")
    return tuple(path for path in candidates if path.is_file())


def _resolve_env_file_path(runtime: Any, key: str, *, base_dir: Path) -> Path | None:
    raw = _raw_without_app_env(runtime, key)
    if raw is None or not str(raw).strip():
        return None
    candidate = Path(str(raw).strip()).expanduser()
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None
    resolved = (base_dir / candidate).resolve()
    return resolved if resolved.is_file() else None


def _raw_without_app_env(runtime: Any, key: str) -> str | None:
    runtime_env = getattr(runtime, "env", None)
    if isinstance(runtime_env, dict) and key in runtime_env:
        value = runtime_env.get(key)
        return str(value) if value else None
    config_raw = getattr(getattr(runtime, "config", None), "raw", None)
    if isinstance(config_raw, dict) and key in config_raw:
        value = config_raw.get(key)
        return str(value) if value else None
    return None


def _read_app_env_file(runtime: Any, path: Path) -> dict[str, str]:
    reader = getattr(runtime, "_read_env_file_safe", None)
    if callable(reader):
        try:
            values = reader(path)
        except Exception:  # noqa: BLE001
            values = None
        if isinstance(values, dict):
            return {str(key): str(value) for key, value in values.items() if value}
    return _read_env_file(path)


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip()
        if not normalized_key:
            continue
        raw_value = value.strip()
        if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {"'", '"'}:
            raw_value = raw_value[1:-1]
        values[normalized_key] = raw_value
    return values


def _copy_present(runtime: Any, env: dict[str, str], keys: tuple[str, ...]) -> None:
    for key in keys:
        value = _raw(runtime, key)
        if value:
            env[key] = value


def _normalize_dependency_id(dependency_id: str) -> str:
    normalized = str(dependency_id).strip().lower().replace("_", "-")
    if normalized == "db":
        normalized = "postgres"
    normalized = normalized.replace("-", "_")
    return normalized if normalized in _DEPENDENCY_IDS else ""


def _parse_dependency_list(raw: object) -> set[str]:
    if raw is None:
        return set()
    dependencies: set[str] = set()
    for token in str(raw).replace(";", ",").replace(" ", ",").split(","):
        normalized = _normalize_dependency_id(token)
        if normalized:
            dependencies.add(normalized)
    return dependencies


def _missing_message(dependency_id: str, keys: tuple[str, ...], runtime: Any) -> str | None:
    missing = tuple(key for key in keys if not _raw(runtime, key))
    if not missing:
        return None
    return _format_missing(dependency_id, missing)


def _format_missing(dependency_id: str, keys: tuple[str, ...]) -> str:
    joined = ", ".join(keys)
    return (
        f"{dependency_id} is configured as an external dependency, but required env var(s) are missing: "
        f"{joined}. Provide them in the shell or .envctl, or remove external mode to let envctl start it."
    )


def _add_url_port(resources: dict[str, int], name: str, raw_url: object) -> None:
    port = _url_port(raw_url)
    if port is not None:
        resources[name] = port


def _url_port(raw_url: object) -> int | None:
    if not raw_url:
        return None
    parsed = urlparse(str(raw_url))
    try:
        if parsed.port is not None:
            return int(parsed.port)
    except ValueError:
        return None
    if parsed.scheme == "https":
        return 443
    if parsed.scheme == "http":
        return 80
    if parsed.scheme in {"postgres", "postgresql", "postgresql+asyncpg", "postgresql+psycopg2"}:
        return 5432
    if parsed.scheme == "redis":
        return 6379
    return None


def _primary_external_port(resources: dict[str, int], definition: DependencyDefinition) -> int | None:
    for resource in definition.resources:
        value = resources.get(resource.name)
        if isinstance(value, int) and value > 0:
            return value
    value = resources.get("primary")
    return value if isinstance(value, int) and value > 0 else None
