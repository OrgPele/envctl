from __future__ import annotations

from envctl_engine.requirements.core.models import DependencyDefinition, DependencyResourceSpec
from envctl_engine.requirements.postgres import start_postgres_container


def project_env(*, runtime, context, requirements, route=None) -> dict[str, str]:
    component = requirements.component("postgres")
    port = component.get("final") or component.get("requested") or int(context.ports["db"].final)
    db_host = runtime._command_override_value("DB_HOST") or "localhost"
    db_user = runtime._command_override_value("DB_USER") or "postgres"
    db_password = runtime._command_override_value("DB_PASSWORD") or "postgres"
    db_name = runtime._command_override_value("DB_NAME") or "postgres"
    return {
        "DB_HOST": db_host,
        "DB_PORT": str(port),
        "DB_USER": db_user,
        "DB_PASSWORD": db_password,
        "DB_NAME": db_name,
        "DATABASE_URL": f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{port}/{db_name}",
    }


DEFINITION = DependencyDefinition(
    id="postgres",
    display_name="postgres",
    order=10,
    resources=(DependencyResourceSpec(name="primary", legacy_port_key="db", config_port_keys=("DB_PORT",)),),
    mode_enable_keys={
        "main": ("MAIN_POSTGRES_ENABLE", "POSTGRES_MAIN_ENABLE"),
        "trees": ("TREES_POSTGRES_ENABLE",),
    },
    default_enabled={"main": True, "trees": True},
    env_projector=project_env,
    native_starter=start_postgres_container,
)
