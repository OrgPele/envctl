from __future__ import annotations

from envctl_engine.config.profile_defaults import dependency_default_enabled
from envctl_engine.requirements.core.models import DependencyDefinition, DependencyResourceSpec
from envctl_engine.requirements.supabase import start_supabase_stack
from envctl_engine.shared.dependency_compose_assets import (
    DEFAULT_SUPABASE_JWT_SECRET,
    default_supabase_anon_key,
    default_supabase_service_role_key,
)
from envctl_engine.startup.public_urls import browser_backend_url, resolve_public_host


def project_env(*, runtime, context, requirements, route=None) -> dict[str, str]:
    component = requirements.component("supabase")
    resources = component.get("resources") if isinstance(component.get("resources"), dict) else {}
    port = resources.get("db") or component.get("final") or component.get("requested") or int(context.ports["db"].final)
    public_port = resources.get("api") or _context_port(context, "supabase_api") or port
    db_host = runtime._command_override_value("DB_HOST") or "localhost"
    db_user = runtime._command_override_value("DB_USER") or "postgres"
    db_password = runtime._command_override_value("SUPABASE_DB_PASSWORD") or "supabase-db-password"
    db_name = runtime._command_override_value("DB_NAME") or "postgres"
    jwt_secret = runtime._command_override_value("SUPABASE_JWT_SECRET") or DEFAULT_SUPABASE_JWT_SECRET
    anon_key = runtime._command_override_value("SUPABASE_ANON_KEY") or default_supabase_anon_key(secret=jwt_secret)
    service_role_key = runtime._command_override_value(
        "SUPABASE_SERVICE_ROLE_KEY"
    ) or default_supabase_service_role_key(secret=jwt_secret)
    database_url = f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{port}/{db_name}"
    public_url = browser_backend_url(
        host=resolve_public_host(env=getattr(runtime, "env", None), config=getattr(runtime, "config", None)),
        port=int(public_port),
    )
    return {
        "DB_HOST": db_host,
        "DB_PORT": str(port),
        "DB_USER": db_user,
        "DB_PASSWORD": db_password,
        "DB_NAME": db_name,
        "DATABASE_URL": database_url,
        "SQLALCHEMY_DATABASE_URL": database_url,
        "ASYNC_DATABASE_URL": database_url,
        "SUPABASE_DB_PASSWORD": db_password,
        "SUPABASE_DB_PORT": str(port),
        "SUPABASE_PUBLIC_PORT": str(public_port),
        "SUPABASE_API_PORT": str(public_port),
        "SUPABASE_PUBLIC_URL": public_url,
        "SUPABASE_URL": public_url,
        "SUPABASE_ANON_KEY": anon_key,
        "SUPABASE_SERVICE_ROLE_KEY": service_role_key,
        "SUPABASE_JWT_SECRET": jwt_secret,
        "SUPABASE_JWKS_URL": f"{public_url}/auth/v1/.well-known/jwks.json",
    }


def _context_port(context, name: str) -> int | None:
    ports = getattr(context, "ports", {})
    if not isinstance(ports, dict):
        return None
    plan = ports.get(name)
    value = getattr(plan, "final", None)
    return int(value) if isinstance(value, int) and value > 0 else None


DEFINITION = DependencyDefinition(
    id="supabase",
    display_name="supabase",
    order=30,
    resources=(
        DependencyResourceSpec(name="db", legacy_port_key="db", config_port_keys=("DB_PORT",)),
        DependencyResourceSpec(
            name="api",
            legacy_port_key="supabase_api",
            config_port_keys=("SUPABASE_PUBLIC_PORT", "SUPABASE_API_PORT"),
            display_name="Supabase API",
        ),
    ),
    mode_enable_keys={
        "main": ("MAIN_SUPABASE_ENABLE", "SUPABASE_MAIN_ENABLE"),
        "trees": ("TREES_SUPABASE_ENABLE",),
    },
    default_enabled={
        "main": dependency_default_enabled("supabase", "main"),
        "trees": dependency_default_enabled("supabase", "trees"),
    },
    env_projector=project_env,
    native_starter=start_supabase_stack,
)
