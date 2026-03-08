from __future__ import annotations

from envctl_engine.requirements.core.models import DependencyDefinition, DependencyResourceSpec
from envctl_engine.requirements.n8n import start_n8n_container


def project_env(*, runtime, context, requirements, route=None) -> dict[str, str]:
    component = requirements.component("n8n")
    port = component.get("final") or component.get("requested") or int(context.ports["n8n"].final)
    return {
        "N8N_PORT": str(port),
        "N8N_URL": f"http://localhost:{port}",
    }


DEFINITION = DependencyDefinition(
    id="n8n",
    display_name="n8n",
    order=40,
    resources=(DependencyResourceSpec(name="primary", legacy_port_key="n8n", config_port_keys=("N8N_PORT_BASE",)),),
    mode_enable_keys={
        "main": ("MAIN_N8N_ENABLE", "N8N_MAIN_ENABLE", "N8N_ENABLE"),
        "trees": ("TREES_N8N_ENABLE", "N8N_ENABLE"),
    },
    default_enabled={"main": False, "trees": True},
    env_projector=project_env,
    native_starter=start_n8n_container,
    health_label="n8n",
)
