from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from envctl_engine.requirements.core.models import DependencyDefinition


DEPENDENCY_IDS = {"postgres", "redis", "supabase", "n8n"}


class ExternalDependencyEnvResolver:
    """Resolves externally managed dependency configuration from envctl and app env files."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def resources(self, definition: DependencyDefinition) -> dict[str, int]:
        dependency = definition.id
        resources: dict[str, int] = {}
        if dependency == "postgres":
            self._add_url_port(resources, "primary", self.raw("DATABASE_URL"))
        elif dependency == "redis":
            self._add_url_port(resources, "primary", self.raw("REDIS_URL"))
        elif dependency == "n8n":
            self._add_url_port(resources, "primary", self.raw("N8N_URL"))
        elif dependency == "supabase":
            self._add_url_port(resources, "api", self.raw("SUPABASE_URL") or self.raw("SUPABASE_PUBLIC_URL"))
            self._add_url_port(resources, "db", self.raw("DATABASE_URL"))
        for resource in definition.resources:
            value = resources.get(resource.name)
            if isinstance(value, int) and value > 0:
                resources.setdefault("primary", value)
                resources.setdefault("requested", value)
                break
        return resources

    def project_env(self, dependency_id: str) -> dict[str, str]:
        dependency = normalize_dependency_id(dependency_id)
        if dependency == "postgres":
            return self._postgres_env()
        if dependency == "redis":
            return self._redis_env()
        if dependency == "n8n":
            return self._n8n_env()
        if dependency == "supabase":
            return self._supabase_env()
        return {}

    def validation_error(self, dependency_id: str) -> str | None:
        dependency = normalize_dependency_id(dependency_id)
        if dependency == "postgres":
            return self._missing_message("postgres", ("DATABASE_URL",))
        if dependency == "redis":
            return self._missing_message("redis", ("REDIS_URL",))
        if dependency == "n8n":
            return self._missing_message("n8n", ("N8N_URL",))
        if dependency == "supabase":
            missing = []
            if not (self.raw("SUPABASE_URL") or self.raw("SUPABASE_PUBLIC_URL")):
                missing.append("SUPABASE_URL")
            if not self.supabase_anon_key():
                missing.append("SUPABASE_ANON_KEY")
            if missing:
                return format_missing(dependency, tuple(missing))
        return None

    def url(self, dependency_id: str) -> str | None:
        dependency = normalize_dependency_id(dependency_id)
        if dependency == "postgres":
            return self.raw("DATABASE_URL")
        if dependency == "redis":
            return self.raw("REDIS_URL")
        if dependency == "n8n":
            return self.raw("N8N_URL")
        if dependency == "supabase":
            return self.raw("SUPABASE_URL") or self.raw("SUPABASE_PUBLIC_URL")
        return None

    def raw(self, key: str) -> str | None:
        runtime_env = getattr(self.runtime, "env", None)
        if isinstance(runtime_env, dict) and key in runtime_env:
            value = runtime_env.get(key)
            return str(value) if value else None
        config_raw = getattr(getattr(self.runtime, "config", None), "raw", None)
        if isinstance(config_raw, dict) and key in config_raw:
            value = config_raw.get(key)
            return str(value) if value else None
        override = getattr(self.runtime, "_command_override_value", None)
        if callable(override):
            value = override(key)
            if value:
                return str(value)
        app_env_value = self._app_env_value(key)
        if app_env_value:
            return app_env_value
        return None

    def raw_without_app_env(self, key: str) -> str | None:
        runtime_env = getattr(self.runtime, "env", None)
        if isinstance(runtime_env, dict) and key in runtime_env:
            value = runtime_env.get(key)
            return str(value) if value else None
        config_raw = getattr(getattr(self.runtime, "config", None), "raw", None)
        if isinstance(config_raw, dict) and key in config_raw:
            value = config_raw.get(key)
            return str(value) if value else None
        return None

    def supabase_anon_key(self) -> str | None:
        return self.raw("SUPABASE_ANON_KEY") or self.raw("VITE_SUPABASE_ANON_KEY")

    def _postgres_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        database_url = self.raw("DATABASE_URL")
        if database_url:
            env["DATABASE_URL"] = database_url
            env["SQLALCHEMY_DATABASE_URL"] = self.raw("SQLALCHEMY_DATABASE_URL") or database_url
            env["ASYNC_DATABASE_URL"] = self.raw("ASYNC_DATABASE_URL") or database_url
            port = url_port(database_url)
            if port is not None:
                env["DB_PORT"] = str(port)
        self._copy_present(env, ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"))
        return env

    def _redis_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        redis_url = self.raw("REDIS_URL")
        if redis_url:
            env["REDIS_URL"] = redis_url
            port = url_port(redis_url)
            if port is not None:
                env["REDIS_PORT"] = str(port)
        return env

    def _n8n_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        n8n_url = self.raw("N8N_URL")
        if n8n_url:
            env["N8N_URL"] = n8n_url
            port = url_port(n8n_url)
            if port is not None:
                env["N8N_PORT"] = str(port)
        return env

    def _supabase_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        public_url = self.raw("SUPABASE_PUBLIC_URL") or self.raw("SUPABASE_URL")
        supabase_url = self.raw("SUPABASE_URL") or public_url
        anon_key = self.supabase_anon_key()
        if public_url:
            env["SUPABASE_PUBLIC_URL"] = public_url
            port = url_port(public_url)
            if port is not None:
                env["SUPABASE_PUBLIC_PORT"] = str(port)
                env["SUPABASE_API_PORT"] = str(port)
        if supabase_url:
            env["SUPABASE_URL"] = supabase_url
            env.setdefault("SUPABASE_JWKS_URL", f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json")
        if anon_key:
            env["SUPABASE_ANON_KEY"] = anon_key
        self._copy_present(
            env,
            (
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
        env.update(self._postgres_env())
        if "DATABASE_URL" in env:
            db_port = url_port(env["DATABASE_URL"])
            if db_port is not None:
                env["SUPABASE_DB_PORT"] = str(db_port)
                env.setdefault("DB_PORT", str(db_port))
        return env

    def _app_env_value(self, key: str) -> str | None:
        for env_file in self._candidate_app_env_files():
            values = self._read_app_env_file(env_file)
            value = values.get(key)
            if value:
                return value
        return None

    def _candidate_app_env_files(self) -> tuple[Path, ...]:
        config = getattr(self.runtime, "config", None)
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

        add(base_dir / ".env")
        backend_dir = str(getattr(config, "backend_dir_name", "backend") or "backend").strip() or "backend"
        add(base_dir / backend_dir / ".env")
        frontend_dir = str(getattr(config, "frontend_dir_name", "frontend") or "frontend").strip() or "frontend"
        add(base_dir / frontend_dir / ".env")
        return tuple(path for path in candidates if path.is_file())

    def _read_app_env_file(self, path: Path) -> dict[str, str]:
        reader = getattr(self.runtime, "_read_env_file_safe", None)
        if callable(reader):
            try:
                values = reader(path)
            except Exception:  # noqa: BLE001
                values = None
            if isinstance(values, dict):
                return {str(key): str(value) for key, value in values.items() if value}
        return read_env_file(path)

    def _copy_present(self, env: dict[str, str], keys: tuple[str, ...]) -> None:
        for key in keys:
            value = self.raw(key)
            if value:
                env[key] = value

    def _missing_message(self, dependency_id: str, keys: tuple[str, ...]) -> str | None:
        missing = tuple(key for key in keys if not self.raw(key))
        if not missing:
            return None
        return format_missing(dependency_id, missing)

    @staticmethod
    def _add_url_port(resources: dict[str, int], name: str, raw_url: object) -> None:
        port = url_port(raw_url)
        if port is not None:
            resources[name] = port


def external_dependency_resources(runtime: Any, definition: DependencyDefinition) -> dict[str, int]:
    return ExternalDependencyEnvResolver(runtime).resources(definition)


def external_dependency_project_env(runtime: Any, dependency_id: str) -> dict[str, str]:
    return ExternalDependencyEnvResolver(runtime).project_env(dependency_id)


def external_dependency_validation_error(runtime: Any, dependency_id: str) -> str | None:
    return ExternalDependencyEnvResolver(runtime).validation_error(dependency_id)


def external_dependency_url(runtime: Any, dependency_id: str) -> str | None:
    return ExternalDependencyEnvResolver(runtime).url(dependency_id)


def primary_external_port(resources: dict[str, int], definition: DependencyDefinition) -> int | None:
    for resource in definition.resources:
        value = resources.get(resource.name)
        if isinstance(value, int) and value > 0:
            return value
    value = resources.get("primary")
    return value if isinstance(value, int) and value > 0 else None


def normalize_dependency_id(dependency_id: str) -> str:
    normalized = str(dependency_id).strip().lower().replace("_", "-")
    if normalized == "db":
        normalized = "postgres"
    normalized = normalized.replace("-", "_")
    return normalized if normalized in DEPENDENCY_IDS else ""


def parse_dependency_list(raw: object) -> set[str]:
    if raw is None:
        return set()
    dependencies: set[str] = set()
    for token in str(raw).replace(";", ",").replace(" ", ",").split(","):
        normalized = normalize_dependency_id(token)
        if normalized:
            dependencies.add(normalized)
    return dependencies


def format_missing(dependency_id: str, keys: tuple[str, ...]) -> str:
    joined = ", ".join(keys)
    return (
        f"{dependency_id} is configured as an external dependency, but required env var(s) are missing: "
        f"{joined}. Provide them in the shell or .envctl, or remove external mode to let envctl start it."
    )


def read_env_file(path: Path) -> dict[str, str]:
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


def url_port(raw_url: object) -> int | None:
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


__all__ = [
    "DEPENDENCY_IDS",
    "ExternalDependencyEnvResolver",
    "external_dependency_project_env",
    "external_dependency_resources",
    "external_dependency_url",
    "external_dependency_validation_error",
    "format_missing",
    "normalize_dependency_id",
    "parse_dependency_list",
    "primary_external_port",
    "read_env_file",
    "url_port",
]
