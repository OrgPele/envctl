from __future__ import annotations

from collections.abc import Mapping


def positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and value > 0 else None


def component_resource_ports(component_data: Mapping[str, object]) -> dict[str, int]:
    resources = component_data.get("resources")
    if not isinstance(resources, Mapping):
        return {}
    return {str(key): value for key, value in resources.items() if isinstance(value, int) and value > 0}


def component_primary_port(component_data: Mapping[str, object]) -> int | None:
    resources = component_resource_ports(component_data)
    return (
        positive_int(resources.get("primary"))
        or positive_int(component_data.get("final"))
        or positive_int(component_data.get("requested"))
    )


def dependency_display_port(component_name: str, component_data: Mapping[str, object]) -> int | None:
    normalized = str(component_name).strip().lower()
    resources = component_resource_ports(component_data)
    if normalized == "supabase":
        return positive_int(resources.get("api")) or component_primary_port(component_data)
    return component_primary_port(component_data)
