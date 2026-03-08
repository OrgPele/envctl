from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

from envctl_engine.requirements.core import dependency_definition, dependency_definitions, dependency_port_keys, managed_enable_keys
from envctl_engine.shared.parsing import parse_bool, parse_int, strip_quotes

CONFIG_MANAGED_BLOCK_START = "# >>> envctl managed startup config >>>"
CONFIG_MANAGED_BLOCK_END = "# <<< envctl managed startup config <<<"
CONFIG_PRIMARY_FILENAME = ".envctl"
LEGACY_CONFIG_FILENAMES = (".envctl.sh", ".supportopia-config")

DEFAULTS: dict[str, str] = {
    "ENVCTL_DEFAULT_MODE": "main",
    "BACKEND_DIR": "backend",
    "FRONTEND_DIR": "frontend",
    "ENVCTL_PLANNING_DIR": "docs/planning",
    "TREES_DIR_NAME": "trees",
    "RUN_SH_RUNTIME_DIR": "/tmp/envctl-runtime",
    "BACKEND_PORT_BASE": "8000",
    "FRONTEND_PORT_BASE": "9000",
    "PORT_SPACING": "20",
    "DB_PORT": "5432",
    "REDIS_PORT": "6379",
    "N8N_PORT_BASE": "5678",
    "POSTGRES_MAIN_ENABLE": "true",
    "REDIS_ENABLE": "true",
    "REDIS_MAIN_ENABLE": "true",
    "SUPABASE_MAIN_ENABLE": "false",
    "N8N_ENABLE": "true",
    "N8N_MAIN_ENABLE": "false",
    "ENVCTL_ENGINE_SHELL_FALLBACK": "false",
    "ENVCTL_STRICT_N8N_BOOTSTRAP": "false",
    "ENVCTL_PORT_AVAILABILITY_MODE": "auto",
    "ENVCTL_PLAN_STRICT_SELECTION": "false",
    "ENVCTL_RUNTIME_TRUTH_MODE": "auto",
    "ENVCTL_REQUIREMENTS_STRICT": "true",
    "ENVCTL_BACKEND_BOOTSTRAP_STRICT": "false",
    "ENVCTL_STATE_COMPAT_MODE": "compat_read_write",
    "ENVCTL_SHELL_PRUNE_MAX_UNMIGRATED": "0",
    "ENVCTL_SHELL_PRUNE_MAX_PARTIAL_KEEP": "0",
    "ENVCTL_SHELL_PRUNE_MAX_INTENTIONAL_KEEP": "0",
    "ENVCTL_SHELL_PRUNE_PHASE": "cutover",
    "MAIN_BACKEND_ENABLE": "true",
    "MAIN_FRONTEND_ENABLE": "true",
    "MAIN_POSTGRES_ENABLE": "true",
    "MAIN_REDIS_ENABLE": "true",
    "MAIN_SUPABASE_ENABLE": "false",
    "MAIN_N8N_ENABLE": "false",
    "TREES_BACKEND_ENABLE": "true",
    "TREES_FRONTEND_ENABLE": "true",
    "TREES_POSTGRES_ENABLE": "true",
    "TREES_REDIS_ENABLE": "true",
    "TREES_SUPABASE_ENABLE": "false",
    "TREES_N8N_ENABLE": "true",
}

MANAGED_CONFIG_KEYS: tuple[str, ...] = (
    "ENVCTL_DEFAULT_MODE",
    "BACKEND_DIR",
    "FRONTEND_DIR",
    "BACKEND_PORT_BASE",
    "FRONTEND_PORT_BASE",
    *dependency_port_keys(),
    "PORT_SPACING",
    "MAIN_BACKEND_ENABLE",
    "MAIN_FRONTEND_ENABLE",
    *managed_enable_keys(),
    "TREES_BACKEND_ENABLE",
    "TREES_FRONTEND_ENABLE",
)


@dataclass(slots=True, init=False)
class StartupProfile:
    backend_enable: bool
    frontend_enable: bool
    dependencies: dict[str, bool]

    def __init__(
        self,
        backend_enable: bool,
        frontend_enable: bool,
        postgres_enable: bool | None = None,
        redis_enable: bool | None = None,
        supabase_enable: bool | None = None,
        n8n_enable: bool | None = None,
        *,
        dependencies: dict[str, bool] | None = None,
    ) -> None:
        self.backend_enable = bool(backend_enable)
        self.frontend_enable = bool(frontend_enable)
        if dependencies is not None:
            self.dependencies = {str(key).strip().lower(): bool(value) for key, value in dependencies.items()}
        else:
            self.dependencies = {
                "postgres": bool(postgres_enable),
                "redis": bool(redis_enable),
                "supabase": bool(supabase_enable),
                "n8n": bool(n8n_enable),
            }

    def dependency_enabled(self, dependency_id: str) -> bool:
        return bool(self.dependencies.get(str(dependency_id).strip().lower(), False))

    @property
    def postgres_enable(self) -> bool:
        return self.dependency_enabled("postgres")

    @postgres_enable.setter
    def postgres_enable(self, value: bool) -> None:
        self.dependencies["postgres"] = bool(value)

    @property
    def redis_enable(self) -> bool:
        return self.dependency_enabled("redis")

    @redis_enable.setter
    def redis_enable(self, value: bool) -> None:
        self.dependencies["redis"] = bool(value)

    @property
    def supabase_enable(self) -> bool:
        return self.dependency_enabled("supabase")

    @supabase_enable.setter
    def supabase_enable(self, value: bool) -> None:
        self.dependencies["supabase"] = bool(value)

    @property
    def n8n_enable(self) -> bool:
        return self.dependency_enabled("n8n")

    @n8n_enable.setter
    def n8n_enable(self, value: bool) -> None:
        self.dependencies["n8n"] = bool(value)


@dataclass(slots=True, init=False)
class PortDefaults:
    backend_port_base: int
    frontend_port_base: int
    dependency_ports: dict[str, dict[str, int]]
    port_spacing: int

    def __init__(
        self,
        backend_port_base: int,
        frontend_port_base: int,
        db_port_base: int | None = None,
        redis_port_base: int | None = None,
        n8n_port_base: int | None = None,
        port_spacing: int = 20,
        *,
        dependency_ports: dict[str, dict[str, int]] | None = None,
    ) -> None:
        self.backend_port_base = int(backend_port_base)
        self.frontend_port_base = int(frontend_port_base)
        self.port_spacing = int(port_spacing)
        if dependency_ports is not None:
            self.dependency_ports = {
                str(key).strip().lower(): {str(resource): int(value) for resource, value in resource_map.items()}
                for key, resource_map in dependency_ports.items()
            }
        else:
            self.dependency_ports = {
                "postgres": {"primary": int(db_port_base or 5432)},
                "redis": {"primary": int(redis_port_base or 6379)},
                "supabase": {"db": int(db_port_base or 5432)},
                "n8n": {"primary": int(n8n_port_base or 5678)},
            }

    def dependency_port(self, dependency_id: str, resource_name: str = "primary") -> int:
        component = self.dependency_ports.get(str(dependency_id).strip().lower(), {})
        return int(component.get(resource_name, 0) or 0)

    @property
    def db_port_base(self) -> int:
        return self.dependency_port("postgres")

    @property
    def redis_port_base(self) -> int:
        return self.dependency_port("redis")

    @property
    def n8n_port_base(self) -> int:
        return self.dependency_port("n8n")


@dataclass(slots=True)
class LocalConfigState:
    base_dir: Path
    config_file_path: Path
    config_file_exists: bool
    config_source: Literal["envctl", "legacy_prefill", "defaults"]
    active_source_path: Path | None
    legacy_source_path: Path | None
    explicit_path: Path | None
    parsed_values: dict[str, str]
    file_text: str


@dataclass(slots=True)
class EngineConfig:
    base_dir: Path
    backend_dir_name: str
    frontend_dir_name: str
    runtime_dir: Path
    runtime_scope_id: str
    runtime_scope_dir: Path
    planning_dir: Path
    trees_dir_name: str
    default_mode: str
    backend_port_base: int
    frontend_port_base: int
    port_spacing: int
    db_port_base: int
    redis_port_base: int
    n8n_port_base: int
    postgres_main_enable: bool
    redis_enable: bool
    redis_main_enable: bool
    supabase_main_enable: bool
    n8n_enable: bool
    n8n_main_enable: bool
    strict_n8n_bootstrap: bool
    port_availability_mode: str
    plan_strict_selection: bool
    runtime_truth_mode: str
    requirements_strict: bool
    main_profile: StartupProfile
    trees_profile: StartupProfile
    port_defaults: PortDefaults
    config_file_path: Path
    config_file_exists: bool
    config_source: Literal["envctl", "legacy_prefill", "defaults"]
    raw: dict[str, str]

    def profile_for_mode(self, mode: str) -> StartupProfile:
        return self.trees_profile if str(mode).strip().lower() == "trees" else self.main_profile

    def service_enabled_for_mode(self, mode: str, service_name: str) -> bool:
        profile = self.profile_for_mode(mode)
        normalized = str(service_name).strip().lower()
        if normalized == "backend":
            return profile.backend_enable
        if normalized == "frontend":
            return profile.frontend_enable
        return False

    def requirement_enabled_for_mode(self, mode: str, requirement_name: str) -> bool:
        profile = self.profile_for_mode(mode)
        return profile.dependency_enabled(str(requirement_name).strip().lower())


def load_config(env: Mapping[str, str] | None = None) -> EngineConfig:
    env = env or {}
    base_dir = Path(env.get("RUN_REPO_ROOT") or Path.cwd()).resolve()
    local_state = discover_local_config_state(base_dir, env.get("ENVCTL_CONFIG_FILE"))

    resolved: dict[str, str] = dict(DEFAULTS)
    for key, value in local_state.parsed_values.items():
        if key not in env:
            resolved[key] = value
    for key, value in env.items():
        resolved[key] = value
    explicit_values: dict[str, str] = dict(local_state.parsed_values)
    explicit_values.update(env)

    default_mode = resolved.get("ENVCTL_DEFAULT_MODE", "main").strip().lower()
    if default_mode not in {"main", "trees"}:
        default_mode = "main"

    runtime_dir = _resolve_path(base_dir, resolved.get("RUN_SH_RUNTIME_DIR", DEFAULTS["RUN_SH_RUNTIME_DIR"]))
    planning_dir = _resolve_path(base_dir, resolved.get("ENVCTL_PLANNING_DIR", DEFAULTS["ENVCTL_PLANNING_DIR"]))
    runtime_scope_id = _runtime_scope_id(base_dir=base_dir, env=env, resolved=resolved)
    runtime_scope_dir = runtime_dir / "python-engine" / runtime_scope_id

    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_scope_dir.mkdir(parents=True, exist_ok=True)

    dependency_ports: dict[str, dict[str, int]] = {}
    for definition in dependency_definitions():
        resources: dict[str, int] = {}
        for resource in definition.resources:
            default_value = 0
            if resource.config_port_keys:
                default_value = _default_port_value(resource.config_port_keys[0])
            raw_value = None
            for key in resource.config_port_keys:
                if key in resolved:
                    raw_value = resolved.get(key)
                    break
            resources[resource.name] = parse_int(raw_value, default_value)
        dependency_ports[definition.id] = resources
    port_defaults = PortDefaults(
        backend_port_base=parse_int(resolved.get("BACKEND_PORT_BASE"), 8000),
        frontend_port_base=parse_int(resolved.get("FRONTEND_PORT_BASE"), 9000),
        dependency_ports=dependency_ports,
        port_spacing=parse_int(resolved.get("PORT_SPACING"), 20),
    )

    main_profile = _startup_profile_from_resolved(resolved, explicit_values=explicit_values, mode="main")
    trees_profile = _startup_profile_from_resolved(resolved, explicit_values=explicit_values, mode="trees")
    if "REDIS_ENABLE" in explicit_values and not parse_bool(explicit_values.get("REDIS_ENABLE"), True):
        main_profile.redis_enable = False
        trees_profile.redis_enable = False
    if "N8N_ENABLE" in explicit_values and not parse_bool(explicit_values.get("N8N_ENABLE"), True):
        main_profile.n8n_enable = False
        trees_profile.n8n_enable = False

    redis_enabled_any = main_profile.redis_enable or trees_profile.redis_enable
    n8n_enabled_any = main_profile.n8n_enable or trees_profile.n8n_enable

    return EngineConfig(
        base_dir=base_dir,
        backend_dir_name=str(resolved.get("BACKEND_DIR", DEFAULTS["BACKEND_DIR"]) or DEFAULTS["BACKEND_DIR"]).strip() or DEFAULTS["BACKEND_DIR"],
        frontend_dir_name=str(resolved.get("FRONTEND_DIR", DEFAULTS["FRONTEND_DIR"]) or DEFAULTS["FRONTEND_DIR"]).strip() or DEFAULTS["FRONTEND_DIR"],
        runtime_dir=runtime_dir,
        runtime_scope_id=runtime_scope_id,
        runtime_scope_dir=runtime_scope_dir,
        planning_dir=planning_dir,
        trees_dir_name=resolved.get("TREES_DIR_NAME", DEFAULTS["TREES_DIR_NAME"]),
        default_mode=default_mode,
        backend_port_base=port_defaults.backend_port_base,
        frontend_port_base=port_defaults.frontend_port_base,
        port_spacing=port_defaults.port_spacing,
        db_port_base=port_defaults.db_port_base,
        redis_port_base=port_defaults.redis_port_base,
        n8n_port_base=port_defaults.n8n_port_base,
        postgres_main_enable=main_profile.postgres_enable,
        redis_enable=redis_enabled_any,
        redis_main_enable=main_profile.redis_enable,
        supabase_main_enable=main_profile.supabase_enable,
        n8n_enable=n8n_enabled_any,
        n8n_main_enable=main_profile.n8n_enable,
        strict_n8n_bootstrap=parse_bool(resolved.get("ENVCTL_STRICT_N8N_BOOTSTRAP"), False),
        port_availability_mode=_parse_port_availability_mode(
            resolved.get("ENVCTL_PORT_AVAILABILITY_MODE"),
            DEFAULTS["ENVCTL_PORT_AVAILABILITY_MODE"],
        ),
        plan_strict_selection=parse_bool(resolved.get("ENVCTL_PLAN_STRICT_SELECTION"), False),
        runtime_truth_mode=_parse_runtime_truth_mode(
            resolved.get("ENVCTL_RUNTIME_TRUTH_MODE"),
            DEFAULTS["ENVCTL_RUNTIME_TRUTH_MODE"],
        ),
        requirements_strict=parse_bool(resolved.get("ENVCTL_REQUIREMENTS_STRICT"), True),
        main_profile=main_profile,
        trees_profile=trees_profile,
        port_defaults=port_defaults,
        config_file_path=local_state.config_file_path,
        config_file_exists=local_state.config_file_exists,
        config_source=local_state.config_source,
        raw=resolved,
    )


def discover_local_config_state(base_dir: Path, explicit_path: str | None = None) -> LocalConfigState:
    base_dir = Path(base_dir).resolve()
    resolved_explicit = _resolve_explicit_path(base_dir, explicit_path)
    primary_path = base_dir / CONFIG_PRIMARY_FILENAME
    file_path = primary_path
    file_exists = primary_path.is_file()
    source: Literal["envctl", "legacy_prefill", "defaults"] = "envctl" if file_exists else "defaults"
    active_source_path: Path | None = primary_path if file_exists else None
    legacy_source_path: Path | None = None

    if resolved_explicit is not None and resolved_explicit.is_file():
        active_source_path = resolved_explicit
        if resolved_explicit.name == CONFIG_PRIMARY_FILENAME:
            file_path = resolved_explicit
            file_exists = True
            source = "envctl"
        else:
            file_exists = primary_path.is_file()
            source = "legacy_prefill" if not file_exists else "envctl"
            legacy_source_path = resolved_explicit
    elif file_exists:
        source = "envctl"
    else:
        for candidate_name in LEGACY_CONFIG_FILENAMES:
            candidate = base_dir / candidate_name
            if candidate.is_file():
                active_source_path = candidate
                legacy_source_path = candidate
                source = "legacy_prefill"
                break

    file_text = ""
    parsed_values: dict[str, str] = {}
    if active_source_path is not None and active_source_path.is_file():
        try:
            file_text = active_source_path.read_text(encoding="utf-8")
        except OSError:
            file_text = ""
        parsed_values = _parse_envctl_text(file_text)

    return LocalConfigState(
        base_dir=base_dir,
        config_file_path=file_path,
        config_file_exists=file_exists,
        config_source=source,
        active_source_path=active_source_path,
        legacy_source_path=legacy_source_path,
        explicit_path=resolved_explicit,
        parsed_values=parsed_values,
        file_text=file_text,
    )


def _startup_profile_from_resolved(
    resolved: Mapping[str, str],
    *,
    explicit_values: Mapping[str, str],
    mode: Literal["main", "trees"],
) -> StartupProfile:
    prefix = "MAIN" if mode == "main" else "TREES"
    def profile_bool(key: str, default: bool) -> bool:
        if key in explicit_values:
            return parse_bool(resolved.get(key), default)
        return default
    dependencies: dict[str, bool] = {}
    for definition in dependency_definitions():
        default = definition.enabled_by_default(mode)
        value = default
        for key in definition.enable_keys_for_mode(mode):
            if key not in explicit_values:
                continue
            value = parse_bool(resolved.get(key), default)
            break
        dependencies[definition.id] = value
    return StartupProfile(
        backend_enable=profile_bool(f"{prefix}_BACKEND_ENABLE", True),
        frontend_enable=profile_bool(f"{prefix}_FRONTEND_ENABLE", True),
        dependencies=dependencies,
    )


def _default_port_value(key: str) -> int:
    defaults = {
        "DB_PORT": 5432,
        "REDIS_PORT": 6379,
        "N8N_PORT_BASE": 5678,
    }
    return defaults.get(key, 0)


def _runtime_scope_id(*, base_dir: Path, env: Mapping[str, str], resolved: Mapping[str, str]) -> str:
    explicit = (env.get("ENVCTL_RUNTIME_SCOPE_ID") or resolved.get("ENVCTL_RUNTIME_SCOPE_ID") or "").strip()
    if explicit:
        normalized = "".join(ch for ch in explicit.lower() if ch.isalnum() or ch in {"-", "_"})
        return normalized or "repo"
    digest = hashlib.sha256(str(base_dir).encode("utf-8")).hexdigest()[:12]
    return f"repo-{digest}"


def _resolve_explicit_path(base_dir: Path, explicit_path: str | None) -> Path | None:
    if not explicit_path:
        return None
    path = Path(explicit_path).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _parse_envctl_text(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = strip_quotes(value.strip())
    return parsed


def _resolve_path(base_dir: Path, raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _parse_port_availability_mode(value: str | None, default: str) -> str:
    if value is None:
        return default
    normalized = value.strip().lower()
    allowed = {"auto", "socket_bind", "listener_query", "lock_only"}
    if normalized in allowed:
        return normalized
    return default


def _parse_runtime_truth_mode(value: str | None, default: str) -> str:
    if value is None:
        return default
    normalized = value.strip().lower()
    allowed = {"auto", "strict", "best_effort"}
    if normalized in allowed:
        return normalized
    return default
