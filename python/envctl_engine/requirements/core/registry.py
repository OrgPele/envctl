from __future__ import annotations

from envctl_engine.requirements.core.models import DependencyDefinition
from envctl_engine.requirements.dependencies.n8n import DEFINITION as N8N_DEFINITION
from envctl_engine.requirements.dependencies.postgres import DEFINITION as POSTGRES_DEFINITION
from envctl_engine.requirements.dependencies.redis import DEFINITION as REDIS_DEFINITION
from envctl_engine.requirements.dependencies.supabase import DEFINITION as SUPABASE_DEFINITION

_BUILTINS: tuple[DependencyDefinition, ...] = tuple(
    sorted(
        (POSTGRES_DEFINITION, REDIS_DEFINITION, SUPABASE_DEFINITION, N8N_DEFINITION),
        key=lambda item: (item.order, item.id),
    )
)
_BY_ID: dict[str, DependencyDefinition] = {definition.id: definition for definition in _BUILTINS}


def dependency_definitions() -> tuple[DependencyDefinition, ...]:
    return _BUILTINS


def dependency_definition(dependency_id: str) -> DependencyDefinition:
    return _BY_ID[str(dependency_id).strip().lower()]


def dependency_ids() -> tuple[str, ...]:
    return tuple(definition.id for definition in _BUILTINS)


def dependency_enable_keys() -> tuple[str, ...]:
    keys: list[str] = []
    seen: set[str] = set()
    for definition in _BUILTINS:
        for mode in ("main", "trees"):
            for key in definition.enable_keys_for_mode(mode):
                if key in seen:
                    continue
                seen.add(key)
                keys.append(key)
    return tuple(keys)


def managed_enable_keys() -> tuple[str, ...]:
    keys: list[str] = []
    for definition in _BUILTINS:
        for mode in ("main", "trees"):
            canonical = next(iter(definition.enable_keys_for_mode(mode)), None)
            if canonical is not None:
                keys.append(canonical)
    return tuple(keys)


def dependency_port_keys() -> tuple[str, ...]:
    keys: list[str] = []
    seen: set[str] = set()
    for definition in _BUILTINS:
        for resource in definition.resources:
            for key in resource.config_port_keys:
                if key in seen:
                    continue
                seen.add(key)
                keys.append(key)
    return tuple(keys)
