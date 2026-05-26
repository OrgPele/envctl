from __future__ import annotations

import json
import re
from typing import Mapping

from envctl_engine.config.models import AppServiceConfig, SupabaseAuthUserConfig
from envctl_engine.shared.parsing import parse_bool, parse_int


_SERVICE_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_SUPABASE_AUTH_USER_SLUG_RE = _SERVICE_SLUG_RE
_RESERVED_SERVICE_NAMES = {
    "backend",
    "frontend",
    "postgres",
    "redis",
    "supabase",
    "n8n",
    "all",
    "services",
    "dependencies",
}


def _parse_additional_services(resolved: Mapping[str, str]) -> tuple[tuple[AppServiceConfig, ...], tuple[str, ...]]:
    declared = [
        item.strip().lower()
        for item in str(resolved.get("ENVCTL_ADDITIONAL_SERVICES", "") or "").split(",")
        if item.strip()
    ]
    services: list[AppServiceConfig] = []
    errors: list[str] = []
    seen_names: set[str] = set()
    seen_suffixes: set[str] = set()
    for name in declared:
        suffix = _service_env_suffix(name)
        if not _SERVICE_SLUG_RE.fullmatch(name):
            errors.append(f"invalid service slug {name!r}: use lowercase letters, numbers, and hyphens")
            continue
        if name in _RESERVED_SERVICE_NAMES:
            errors.append(f"reserved service name {name!r} cannot be used as an additional app service")
            continue
        if name in seen_names:
            errors.append(f"duplicate service slug {name!r}")
            continue
        if suffix in seen_suffixes:
            errors.append(f"duplicate service env suffix {suffix!r}")
            continue
        prefix = f"ENVCTL_SERVICE_{suffix}_"
        enabled_default = parse_bool(resolved.get(f"{prefix}ENABLE"), True)
        enabled_main = parse_bool(resolved.get(f"{prefix}MAIN_ENABLE"), enabled_default)
        enabled_trees = parse_bool(resolved.get(f"{prefix}TREES_ENABLE"), enabled_default)
        start_cmd = str(resolved.get(f"{prefix}START_CMD", "") or "").strip()
        expect_listener = parse_bool(resolved.get(f"{prefix}EXPECT_LISTENER"), True)
        port_base_raw = str(resolved.get(f"{prefix}PORT_BASE", "") or "").strip()
        port_base = parse_int(port_base_raw, 0) if port_base_raw else None
        if (enabled_main or enabled_trees) and not start_cmd:
            errors.append(f"enabled service {name!r} requires {prefix}START_CMD")
            continue
        if (enabled_main or enabled_trees) and expect_listener and (port_base is None or port_base <= 0):
            errors.append(f"listener service {name!r} requires {prefix}PORT_BASE")
            continue
        seen_names.add(name)
        seen_suffixes.add(suffix)
        services.append(
            AppServiceConfig(
                name=name,
                env_suffix=suffix,
                enabled_main=enabled_main,
                enabled_trees=enabled_trees,
                dir_name=str(resolved.get(f"{prefix}DIR", "") or "").strip() or ".",
                start_cmd=start_cmd,
                test_cmd=str(resolved.get(f"{prefix}TEST_CMD", "") or "").strip(),
                port_base=port_base,
                expect_listener=expect_listener,
                health_url_template=str(resolved.get(f"{prefix}HEALTH_URL", "") or "").strip(),
                public_url_template=str(resolved.get(f"{prefix}PUBLIC_URL", "") or "").strip(),
                startup_group=str(resolved.get(f"{prefix}STARTUP_GROUP", "app") or "app").strip() or "app",
                depends_on=tuple(
                    item.strip().lower()
                    for item in str(resolved.get(f"{prefix}DEPENDS_ON", "") or "").split(",")
                    if item.strip()
                ),
                start_order=parse_int(resolved.get(f"{prefix}START_ORDER"), 100),
                critical=parse_bool(resolved.get(f"{prefix}CRITICAL"), True),
                enable_if_path=str(resolved.get(f"{prefix}ENABLE_IF_PATH", "") or "").strip(),
            )
        )
    dependency_errors = _validate_additional_service_dependencies(services)
    errors.extend(dependency_errors)
    if errors:
        return (), tuple(errors)
    return tuple(services), ()


def _parse_supabase_auth_users(
    resolved: Mapping[str, str],
) -> tuple[tuple[SupabaseAuthUserConfig, ...], tuple[str, ...]]:
    declared = [
        item.strip().lower()
        for item in str(resolved.get("ENVCTL_SUPABASE_AUTH_USERS", "") or "").split(",")
        if item.strip()
    ]
    users: list[SupabaseAuthUserConfig] = []
    errors: list[str] = []
    seen_names: set[str] = set()
    seen_suffixes: set[str] = set()
    for name in declared:
        suffix = _service_env_suffix(name)
        if not _SUPABASE_AUTH_USER_SLUG_RE.fullmatch(name):
            errors.append(f"invalid Supabase Auth user slug {name!r}: use lowercase letters, numbers, and hyphens")
            continue
        if name in seen_names:
            errors.append(f"duplicate Supabase Auth user slug {name!r}")
            continue
        if suffix in seen_suffixes:
            errors.append(f"duplicate Supabase Auth user env suffix {suffix!r}")
            continue
        prefix = f"ENVCTL_SUPABASE_USER_{suffix}_"
        enabled_default = parse_bool(resolved.get(f"{prefix}ENABLE"), True)
        enabled_main = parse_bool(resolved.get(f"{prefix}MAIN_ENABLE"), enabled_default)
        enabled_trees = parse_bool(resolved.get(f"{prefix}TREES_ENABLE"), enabled_default)
        email = str(resolved.get(f"{prefix}EMAIL", "") or "").strip()
        password = str(resolved.get(f"{prefix}PASSWORD", "") or "").strip() or None
        if (enabled_main or enabled_trees) and not email:
            errors.append(f"Supabase Auth user {name!r} requires {prefix}EMAIL")
        if (enabled_main or enabled_trees) and password is None:
            errors.append(f"Supabase Auth user {name!r} requires {prefix}PASSWORD or runtime password env")
        user_metadata, user_metadata_error = _parse_json_object_value(
            resolved.get(f"{prefix}USER_METADATA_JSON"),
            key=f"{prefix}USER_METADATA_JSON",
        )
        if user_metadata_error:
            errors.append(user_metadata_error)
        app_metadata, app_metadata_error = _parse_json_object_value(
            resolved.get(f"{prefix}APP_METADATA_JSON"),
            key=f"{prefix}APP_METADATA_JSON",
        )
        if app_metadata_error:
            errors.append(app_metadata_error)
        seen_names.add(name)
        seen_suffixes.add(suffix)
        users.append(
            SupabaseAuthUserConfig(
                name=name,
                env_suffix=suffix,
                email=email,
                password=password,
                auto_confirm=parse_bool(resolved.get(f"{prefix}AUTO_CONFIRM"), True),
                user_metadata=user_metadata,
                app_metadata=app_metadata,
                enabled_main=enabled_main,
                enabled_trees=enabled_trees,
                delete_on_blast=parse_bool(resolved.get(f"{prefix}DELETE_ON_BLAST"), False),
                expose_password=parse_bool(resolved.get(f"{prefix}EXPOSE_PASSWORD"), True),
            )
        )
    return tuple(users), tuple(errors)


def _parse_json_object_value(raw: object, *, key: str) -> tuple[dict[str, object], str | None]:
    text = str(raw or "").strip()
    if not text:
        return {}, None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"{key} must be a JSON object: {exc.msg}"
    if not isinstance(payload, dict):
        return {}, f"{key} must be a JSON object"
    return dict(payload), None


def _validate_additional_service_dependencies(services: list[AppServiceConfig]) -> list[str]:
    from envctl_engine.requirements.core import dependency_ids

    errors: list[str] = []
    service_names = {service.name for service in services}
    allowed = {"backend", "frontend", *dependency_ids(), *service_names}
    graph: dict[str, set[str]] = {service.name: set() for service in services}
    for service in services:
        for dependency in service.depends_on:
            if dependency not in allowed:
                errors.append(
                    f"service {service.name!r} depends on unknown service or dependency {dependency!r}"
                )
                continue
            if dependency in service_names:
                graph[service.name].add(dependency)

    visiting: list[str] = []
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            cycle = [*visiting[visiting.index(name) :], name]
            errors.append("additional service dependency cycle: " + " -> ".join(cycle))
            return
        visiting.append(name)
        for dependency in sorted(graph.get(name, set())):
            visit(dependency)
        visiting.pop()
        visited.add(name)

    for service in services:
        visit(service.name)
    return errors


def _service_env_suffix(service_name: str) -> str:
    return str(service_name).strip().upper().replace("-", "_")

