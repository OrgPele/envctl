from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal, Mapping

from envctl_engine.config.dependency_env_templates import DependencyEnvTemplateEntry
from envctl_engine.config.models import LocalConfigState, StartupProfile
from envctl_engine.config.profile_defaults import managed_dependency_default_enabled
from envctl_engine.shared.parsing import parse_bool


def _dependency_definitions():
    from envctl_engine.requirements.core import dependency_definitions

    return dependency_definitions()


_POSTGRES_TEMPLATE_SOURCE_TOKENS = (
    "${ENVCTL_SOURCE_DATABASE_URL}",
    "${ENVCTL_SOURCE_SQLALCHEMY_DATABASE_URL}",
    "${ENVCTL_SOURCE_ASYNC_DATABASE_URL}",
    "${ENVCTL_SOURCE_DB_HOST}",
    "${ENVCTL_SOURCE_DB_PORT}",
    "${ENVCTL_SOURCE_DB_USER}",
    "${ENVCTL_SOURCE_DB_PASSWORD}",
    "${ENVCTL_SOURCE_DB_NAME}",
)
_REDIS_TEMPLATE_SOURCE_TOKENS = (
    "${ENVCTL_SOURCE_REDIS_URL}",
    "${ENVCTL_SOURCE_REDIS_PORT}",
)
_SUPABASE_TEMPLATE_SOURCE_TOKENS = (
    "${ENVCTL_SOURCE_SUPABASE_URL}",
    "${ENVCTL_SOURCE_SUPABASE_PUBLIC_URL}",
    "${ENVCTL_SOURCE_SUPABASE_PUBLIC_PORT}",
    "${ENVCTL_SOURCE_SUPABASE_API_PORT}",
    "${ENVCTL_SOURCE_SUPABASE_ANON_KEY}",
    "${ENVCTL_SOURCE_SUPABASE_SERVICE_ROLE_KEY}",
    "${ENVCTL_SOURCE_SUPABASE_JWT_SECRET}",
    "${ENVCTL_SOURCE_SUPABASE_JWKS_URL}",
    "${ENVCTL_SOURCE_SUPABASE_DB_PASSWORD}",
    "${ENVCTL_SOURCE_SUPABASE_DB_PORT}",
    "${ENVCTL_SOURCE_SUPABASE_TEST_USER_ID}",
    "${ENVCTL_SOURCE_SUPABASE_TEST_USER_EMAIL}",
    "${ENVCTL_SOURCE_SUPABASE_TEST_USER_PASSWORD}",
)
_SUPABASE_TEMPLATE_SOURCE_PREFIX_TOKENS = (
    "${ENVCTL_SOURCE_SUPABASE_USER_",
)


def _apply_dependency_env_template_inferences(
    profile: StartupProfile,
    *,
    mode: Literal["main", "trees"],
    explicit_values: Mapping[str, str],
    local_state: LocalConfigState,
) -> None:
    """Enable core dynamic dependencies needed by active launch env templates.

    A saved `.envctl` file can contain backend/frontend launch env templates without
    the older managed dependency toggles. In that shape the template is an active
    request for envctl-owned dynamic URLs, so keep PostgreSQL/Redis dynamic by
    default while still honoring explicit dependency enable/disable keys.
    """

    if not profile.startup_enable:
        return
    inferred = _core_dependencies_referenced_by_launch_env_templates(
        local_state,
        mode=mode,
        backend_enabled=profile.backend_enable,
        frontend_enabled=profile.frontend_enable,
    )
    supabase_can_be_enabled = "supabase" in inferred and not _dependency_toggle_explicit_for_mode(
        "supabase", mode=mode, explicit_values=explicit_values
    )
    for dependency_id in sorted(inferred):
        if _dependency_toggle_explicit_for_mode(dependency_id, mode=mode, explicit_values=explicit_values):
            continue
        if dependency_id == "postgres" and (profile.supabase_enable or supabase_can_be_enabled):
            continue
        profile.dependencies[dependency_id] = True


def _core_dependencies_referenced_by_launch_env_templates(
    local_state: LocalConfigState,
    *,
    mode: Literal["main", "trees"],
    backend_enabled: bool,
    frontend_enabled: bool,
) -> set[str]:
    entries: list[DependencyEnvTemplateEntry] = []
    if backend_enabled:
        entries.extend(local_state.dependency_env_templates)
        entries.extend(local_state.backend_dependency_env_templates)
        if mode == "main":
            entries.extend(local_state.main_backend_dependency_env_templates)
        else:
            entries.extend(local_state.trees_backend_dependency_env_templates)
    if frontend_enabled:
        entries.extend(local_state.dependency_env_templates)
        entries.extend(local_state.frontend_dependency_env_templates)
        if mode == "main":
            entries.extend(local_state.main_frontend_dependency_env_templates)
        else:
            entries.extend(local_state.trees_frontend_dependency_env_templates)
    inferred: set[str] = set()
    for entry in entries:
        template = entry.template
        if any(token in template for token in _POSTGRES_TEMPLATE_SOURCE_TOKENS):
            inferred.add("postgres")
        if any(token in template for token in _REDIS_TEMPLATE_SOURCE_TOKENS):
            inferred.add("redis")
        if any(token in template for token in _SUPABASE_TEMPLATE_SOURCE_TOKENS) or any(
            token in template for token in _SUPABASE_TEMPLATE_SOURCE_PREFIX_TOKENS
        ):
            inferred.add("supabase")
    return inferred


def _dependency_toggle_explicit_for_mode(
    dependency_id: str,
    *,
    mode: Literal["main", "trees"],
    explicit_values: Mapping[str, str],
) -> bool:
    for definition in _dependency_definitions():
        if definition.id != dependency_id:
            continue
        return any(key in explicit_values for key in definition.enable_keys_for_mode(mode))
    return False


def _apply_plan_agent_aliases(resolved: dict[str, str], *, explicit_values: Mapping[str, str]) -> None:
    if "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE" not in explicit_values and "CMUX" in explicit_values:
        resolved["ENVCTL_PLAN_AGENT_TERMINALS_ENABLE"] = str(explicit_values.get("CMUX", ""))
    if "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE" not in explicit_values and "CMUX_WORKSPACE" in explicit_values:
        resolved["ENVCTL_PLAN_AGENT_CMUX_WORKSPACE"] = str(explicit_values.get("CMUX_WORKSPACE", ""))
    if "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE" not in explicit_values and "SUPERSET" in explicit_values:
        resolved["ENVCTL_PLAN_AGENT_TERMINALS_ENABLE"] = str(explicit_values.get("SUPERSET", ""))
    if "ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT" not in explicit_values and "SUPERSET" in explicit_values:
        if parse_bool(explicit_values.get("SUPERSET"), False):
            resolved["ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT"] = "superset"
    if "ENVCTL_PLAN_AGENT_SUPERSET_PROJECT" not in explicit_values and "SUPERSET_PROJECT" in explicit_values:
        resolved["ENVCTL_PLAN_AGENT_SUPERSET_PROJECT"] = str(explicit_values.get("SUPERSET_PROJECT", ""))
    if "ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT" not in explicit_values and (
        "SUPERSET_PROJECT" in explicit_values or "ENVCTL_PLAN_AGENT_SUPERSET_PROJECT" in explicit_values
    ):
        resolved["ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT"] = "superset"
    if "ENVCTL_PLAN_AGENT_SUPERSET_WORKSPACE" not in explicit_values and "SUPERSET_WORKSPACE" in explicit_values:
        resolved["ENVCTL_PLAN_AGENT_SUPERSET_WORKSPACE"] = str(explicit_values.get("SUPERSET_WORKSPACE", ""))
    if "ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT" not in explicit_values and (
        "SUPERSET_WORKSPACE" in explicit_values or "ENVCTL_PLAN_AGENT_SUPERSET_WORKSPACE" in explicit_values
    ):
        resolved["ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT"] = "superset"
    if "ENVCTL_PLAN_AGENT_CODEX_CYCLES" not in explicit_values and "CYCLES" in explicit_values:
        resolved["ENVCTL_PLAN_AGENT_CODEX_CYCLES"] = str(explicit_values.get("CYCLES", ""))


def _startup_profile_from_resolved(
    resolved: Mapping[str, str],
    *,
    explicit_values: Mapping[str, str],
    mode: Literal["main", "trees"],
    use_managed_dependency_defaults: bool = False,
) -> StartupProfile:
    prefix = "MAIN" if mode == "main" else "TREES"

    def profile_bool(key: str, default: bool) -> bool:
        if key in explicit_values:
            return parse_bool(resolved.get(key), default)
        return default

    dependencies: dict[str, bool] = {}
    for definition in _dependency_definitions():
        if use_managed_dependency_defaults:
            default = managed_dependency_default_enabled(definition.id, mode)
        else:
            default = definition.enabled_by_default(mode)
        value = default
        for key in definition.enable_keys_for_mode(mode):
            if key not in explicit_values:
                continue
            value = parse_bool(resolved.get(key), default)
            break
        dependencies[definition.id] = value
    postgres_key = f"{prefix}_POSTGRES_ENABLE"
    supabase_key = f"{prefix}_SUPABASE_ENABLE"
    if (
        supabase_key in explicit_values
        and parse_bool(resolved.get(supabase_key), False)
        and postgres_key not in explicit_values
    ):
        dependencies["postgres"] = False
    if (
        postgres_key in explicit_values
        and parse_bool(resolved.get(postgres_key), False)
        and supabase_key not in explicit_values
    ):
        dependencies["supabase"] = False
    return StartupProfile(
        startup_enable=profile_bool(f"{prefix}_STARTUP_ENABLE", True),
        backend_enable=profile_bool(f"{prefix}_BACKEND_ENABLE", True),
        frontend_enable=profile_bool(f"{prefix}_FRONTEND_ENABLE", True),
        dependencies=dependencies,
    )


def _default_port_value(key: str) -> int:
    defaults = {
        "DB_PORT": 5432,
        "REDIS_PORT": 6379,
        "N8N_PORT_BASE": 5678,
        "SUPABASE_PUBLIC_PORT": 54321,
        "SUPABASE_API_PORT": 54321,
    }
    return defaults.get(key, 0)


def _runtime_scope_id(*, base_dir: Path, env: Mapping[str, str], resolved: Mapping[str, str]) -> str:
    explicit = (env.get("ENVCTL_RUNTIME_SCOPE_ID") or resolved.get("ENVCTL_RUNTIME_SCOPE_ID") or "").strip()
    if explicit:
        normalized = "".join(ch for ch in explicit.lower() if ch.isalnum() or ch in {"-", "_"})
        return normalized or "repo"
    digest = hashlib.sha256(str(base_dir).encode("utf-8")).hexdigest()[:12]
    return f"repo-{digest}"


def _resolve_path(base_dir: Path, raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _resolve_planning_dir(*, base_dir: Path, execution_root: Path, raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    base_candidate = (base_dir / path).resolve()
    execution_candidate = (execution_root / path).resolve()
    if execution_root.resolve() != base_dir.resolve() and execution_candidate.is_dir():
        return execution_candidate
    return base_candidate


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
