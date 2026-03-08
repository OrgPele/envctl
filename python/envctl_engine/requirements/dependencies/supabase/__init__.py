from __future__ import annotations

from envctl_engine.requirements.core.models import DependencyDefinition, DependencyResourceSpec
from envctl_engine.requirements.supabase import start_supabase_stack


def project_env(*, runtime, context, requirements, route=None) -> dict[str, str]:
    component = requirements.component("supabase")
    port = component.get("final") or component.get("requested") or int(context.ports["db"].final)
    db_host = runtime._command_override_value("DB_HOST") or "localhost"
    db_user = runtime._command_override_value("DB_USER") or "postgres"
    db_password = runtime._command_override_value("SUPABASE_DB_PASSWORD") or "supabase-db-password"
    db_name = runtime._command_override_value("DB_NAME") or "postgres"
    database_url = f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{port}/{db_name}"
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
        "SUPABASE_URL": f"http://localhost:{port}",
    }


DEFINITION = DependencyDefinition(
    id="supabase",
    display_name="supabase",
    order=30,
    resources=(DependencyResourceSpec(name="db", legacy_port_key="db", config_port_keys=("DB_PORT",)),),
    mode_enable_keys={
        "main": ("MAIN_SUPABASE_ENABLE", "SUPABASE_MAIN_ENABLE"),
        "trees": ("TREES_SUPABASE_ENABLE",),
    },
    default_enabled={"main": False, "trees": False},
    env_projector=project_env,
    native_starter=start_supabase_stack,
)
