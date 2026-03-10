from __future__ import annotations

from envctl_engine.config.profile_defaults import dependency_default_enabled
from envctl_engine.requirements.core.models import DependencyDefinition, DependencyResourceSpec
from envctl_engine.requirements.redis import start_redis_container


def project_env(*, runtime, context, requirements, route=None) -> dict[str, str]:
    component = requirements.component("redis")
    port = component.get("final") or component.get("requested") or int(context.ports["redis"].final)
    return {
        "REDIS_PORT": str(port),
        "REDIS_URL": f"redis://localhost:{port}/0",
    }


DEFINITION = DependencyDefinition(
    id="redis",
    display_name="redis",
    order=20,
    resources=(DependencyResourceSpec(name="primary", legacy_port_key="redis", config_port_keys=("REDIS_PORT",)),),
    mode_enable_keys={
        "main": ("MAIN_REDIS_ENABLE", "REDIS_MAIN_ENABLE", "REDIS_ENABLE"),
        "trees": ("TREES_REDIS_ENABLE", "REDIS_ENABLE"),
    },
    default_enabled={
        "main": dependency_default_enabled("redis", "main"),
        "trees": dependency_default_enabled("redis", "trees"),
    },
    env_projector=project_env,
    native_starter=start_redis_container,
)
